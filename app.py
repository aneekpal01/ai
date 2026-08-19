from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3, secrets
from datetime import datetime, timedelta
import qrcode
import io, base64

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

DB = "attendance.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()

@app.route("/")
def index():
    conn = get_db()
    students = conn.execute("SELECT * FROM students ORDER BY roll_no").fetchall()
    conn.close()
    return render_template("index.html", students=students)

@app.route("/add_student", methods=["POST"])
def add_student():
    roll_no = request.form["roll_no"].strip()
    name = request.form["name"].strip()

    if not roll_no or not name:
        flash("Enter both roll number and name.")
        return redirect(url_for("index"))

    conn = get_db()
    try:
        conn.execute("INSERT INTO students (roll_no, name) VALUES (?, ?)",
                     (roll_no, name))
        conn.commit()
        flash("Student added.")
    except sqlite3.IntegrityError:
        flash("That roll number already exists.")
    finally:
        conn.close()
    return redirect(url_for("index"))

@app.route("/teacher")
def teacher():
    conn = get_db()
    sessions = conn.execute(
        "SELECT * FROM sessions ORDER BY id DESC"
    ).fetchall()
    conn.close()

    qr_images = {}
    for s in sessions:
        qr_data = url_for("mark_attendance", token=s["token"], _external=True)
        img = qrcode.make(qr_data)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        qr_images[s["id"]] = base64.b64encode(buffer.getvalue()).decode()

    return render_template("teacher.html", sessions=sessions, qr_images=qr_images)

@app.route("/create_session", methods=["POST"])
def create_session():
    subject = request.form["subject"].strip()
    minutes = int(request.form.get("minutes", 2))

    if not subject:
        flash("Enter a subject.")
        return redirect(url_for("teacher"))

    now = datetime.now()
    expires = now + timedelta(minutes=minutes)
    token = secrets.token_urlsafe(24)

    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (subject, token, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (subject, token, now.isoformat(timespec="seconds"),
         expires.isoformat(timespec="seconds"))
    )
    conn.commit()
    conn.close()

    flash(f"Attendance session created for {subject}. QR expires in {minutes} minute(s).")
    return redirect(url_for("teacher"))

@app.route("/mark/<token>", methods=["GET", "POST"])
def mark_attendance(token):
    conn = get_db()
    att_session = conn.execute(
        "SELECT * FROM sessions WHERE token=?", (token,)
    ).fetchone()

    if not att_session:
        conn.close()
        return "Invalid attendance QR.", 404

    expired = datetime.now() > datetime.fromisoformat(att_session["expires_at"])

    if request.method == "POST":
        if expired:
            conn.close()
            return render_template("mark.html", session=att_session,
                                   error="This QR code has expired.")

        roll_no = request.form["roll_no"].strip()
        student = conn.execute(
            "SELECT * FROM students WHERE roll_no=?", (roll_no,)
        ).fetchone()

        if not student:
            conn.close()
            return render_template("mark.html", session=att_session,
                                   error="Student not found. Ask the teacher to register you.")

        try:
            conn.execute(
                "INSERT INTO attendance (student_id, session_id, marked_at) VALUES (?, ?, ?)",
                (student["id"], att_session["id"],
                 datetime.now().isoformat(timespec="seconds"))
            )
            conn.commit()
            message = f"Attendance marked successfully for {student['name']}."
        except sqlite3.IntegrityError:
            message = "Attendance was already marked for this session."

        conn.close()
        return render_template("mark.html", session=att_session, message=message)

    conn.close()
    return render_template("mark.html", session=att_session, expired=expired)

@app.route("/report")
def report():
    conn = get_db()
    rows = conn.execute("""
        SELECT s.roll_no, s.name,
               COUNT(a.id) AS present,
               (SELECT COUNT(*) FROM sessions) AS total
        FROM students s
        LEFT JOIN attendance a ON s.id = a.student_id
        GROUP BY s.id
        ORDER BY s.roll_no
    """).fetchall()
    conn.close()
    return render_template("report.html", rows=rows)

@app.route("/session/<int:session_id>")
def session_details(session_id):
    conn = get_db()
    att_session = conn.execute(
        "SELECT * FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    rows = conn.execute("""
        SELECT s.roll_no, s.name, a.marked_at
        FROM attendance a
        JOIN students s ON s.id = a.student_id
        WHERE a.session_id=?
        ORDER BY s.roll_no
    """, (session_id,)).fetchall()
    conn.close()

    if not att_session:
        return "Session not found", 404
    return render_template("session.html", session=att_session, rows=rows)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
