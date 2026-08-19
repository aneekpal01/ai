import os
import io
import base64
import secrets
import sqlite3

from datetime import datetime, timedelta

import qrcode
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
)


# ---------------------------------------------------------
# Flask application
# ---------------------------------------------------------

app = Flask(__name__)

# Use a Render environment variable in production.
# The fallback is only for local/demo use.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "smart-attendance-dev-secret-change-in-production",
)

# You can optionally set DB_PATH on Render/local machine.
# Default keeps the existing project behaviour.
DB = os.environ.get("DB_PATH", "attendance.db")


# ---------------------------------------------------------
# Database helpers
# ---------------------------------------------------------

def get_db():
    """Create a SQLite connection with dictionary-like rows."""
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all required tables if they do not already exist."""
    conn = get_db()

    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roll_no TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                marked_at TEXT NOT NULL,
                UNIQUE(student_id, session_id),
                FOREIGN KEY(student_id) REFERENCES students(id),
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


# IMPORTANT:
# Gunicorn imports "app" directly, so code inside
# "if __name__ == '__main__'" is NOT executed by Gunicorn.
# Initializing here makes sure the database exists on Render.
init_db()


# ---------------------------------------------------------
# Home / Student registration
# ---------------------------------------------------------

@app.route("/")
def index():
    conn = get_db()

    try:
        students = conn.execute(
            "SELECT * FROM students ORDER BY roll_no"
        ).fetchall()
    finally:
        conn.close()

    return render_template("index.html", students=students)


@app.route("/add_student", methods=["POST"])
def add_student():
    roll_no = request.form.get("roll_no", "").strip()
    name = request.form.get("name", "").strip()

    if not roll_no or not name:
        flash("Enter both roll number and name.")
        return redirect(url_for("index"))

    conn = get_db()

    try:
        conn.execute(
            "INSERT INTO students (roll_no, name) VALUES (?, ?)",
            (roll_no, name),
        )
        conn.commit()
        flash("Student added.")
    except sqlite3.IntegrityError:
        flash("That roll number already exists.")
    finally:
        conn.close()

    return redirect(url_for("index"))


# ---------------------------------------------------------
# Teacher dashboard
# ---------------------------------------------------------

@app.route("/teacher")
def teacher():
    conn = get_db()

    try:
        sessions = conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()

    qr_images = {}

    for attendance_session in sessions:
        qr_data = url_for(
            "mark_attendance",
            token=attendance_session["token"],
            _external=True,
        )

        img = qrcode.make(qr_data)

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")

        qr_images[attendance_session["id"]] = base64.b64encode(
            buffer.getvalue()
        ).decode("utf-8")

    return render_template(
        "teacher.html",
        sessions=sessions,
        qr_images=qr_images,
    )


@app.route("/create_session", methods=["POST"])
def create_session():
    subject = request.form.get("subject", "").strip()

    # Safely parse minutes instead of allowing ValueError to crash the app.
    try:
        minutes = int(request.form.get("minutes", 2))
    except (TypeError, ValueError):
        minutes = 2

    # Keep the session duration within a sensible range.
    minutes = max(1, min(minutes, 1440))

    if not subject:
        flash("Enter a subject.")
        return redirect(url_for("teacher"))

    now = datetime.now()
    expires = now + timedelta(minutes=minutes)

    # Cryptographically secure random QR token.
    token = secrets.token_urlsafe(24)

    conn = get_db()

    try:
        conn.execute(
            """
            INSERT INTO sessions
                (subject, token, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                subject,
                token,
                now.isoformat(timespec="seconds"),
                expires.isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    flash(
        f"Attendance session created for {subject}. "
        f"QR expires in {minutes} minute(s)."
    )

    return redirect(url_for("teacher"))


# ---------------------------------------------------------
# Attendance marking
# ---------------------------------------------------------

@app.route("/mark/<token>", methods=["GET", "POST"])
def mark_attendance(token):
    conn = get_db()

    try:
        attendance_session = conn.execute(
            "SELECT * FROM sessions WHERE token = ?",
            (token,),
        ).fetchone()

        if not attendance_session:
            return "Invalid attendance QR.", 404

        expired = (
            datetime.now()
            > datetime.fromisoformat(attendance_session["expires_at"])
        )

        if request.method == "POST":
            if expired:
                return render_template(
                    "mark.html",
                    session=attendance_session,
                    error="This QR code has expired.",
                )

            roll_no = request.form.get("roll_no", "").strip()

            if not roll_no:
                return render_template(
                    "mark.html",
                    session=attendance_session,
                    error="Please enter your roll number.",
                )

            student = conn.execute(
                "SELECT * FROM students WHERE roll_no = ?",
                (roll_no,),
            ).fetchone()

            if not student:
                return render_template(
                    "mark.html",
                    session=attendance_session,
                    error=(
                        "Student not found. "
                        "Ask the teacher to register you."
                    ),
                )

            try:
                conn.execute(
                    """
                    INSERT INTO attendance
                        (student_id, session_id, marked_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        student["id"],
                        attendance_session["id"],
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                conn.commit()

                message = (
                    f"Attendance marked successfully for "
                    f"{student['name']}."
                )

            except sqlite3.IntegrityError:
                message = "Attendance was already marked for this session."

            return render_template(
                "mark.html",
                session=attendance_session,
                message=message,
            )

        return render_template(
            "mark.html",
            session=attendance_session,
            expired=expired,
        )

    finally:
        conn.close()


# ---------------------------------------------------------
# Overall attendance report
# ---------------------------------------------------------

@app.route("/report")
def report():
    conn = get_db()

    try:
        rows = conn.execute(
            """
            SELECT
                s.roll_no,
                s.name,
                COUNT(a.id) AS present,
                (SELECT COUNT(*) FROM sessions) AS total
            FROM students s
            LEFT JOIN attendance a
                ON s.id = a.student_id
            GROUP BY s.id
            ORDER BY s.roll_no
            """
        ).fetchall()
    finally:
        conn.close()

    return render_template("report.html", rows=rows)


# ---------------------------------------------------------
# Session details
# ---------------------------------------------------------

@app.route("/session/<int:session_id>")
def session_details(session_id):
    conn = get_db()

    try:
        attendance_session = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

        if not attendance_session:
            return "Session not found", 404

        rows = conn.execute(
            """
            SELECT
                s.roll_no,
                s.name,
                a.marked_at
            FROM attendance a
            JOIN students s
                ON s.id = a.student_id
            WHERE a.session_id = ?
            ORDER BY s.roll_no
            """,
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    return render_template(
        "session.html",
        session=attendance_session,
        rows=rows,
    )


# ---------------------------------------------------------
# Local development
# ---------------------------------------------------------

if __name__ == "__main__":
    # Render/Gunicorn will NOT use this block.
    # It is only for running locally with:
    # python app.py
    port = int(os.environ.get("PORT", 5000))

    app.run(
        debug=True,
        host="0.0.0.0",
        port=port,
    )
