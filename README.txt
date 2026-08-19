SMART ATTENDANCE SYSTEM - BEGINNER HACKATHON VERSION

1. Install Python 3.11+.
2. Open a terminal in this project folder.
3. Create a virtual environment:
   Windows: python -m venv venv
            venv\Scripts\activate
   Linux/macOS: python3 -m venv venv
                source venv/bin/activate

4. Install packages:
   pip install -r requirements.txt

5. Start the server:
   python app.py

6. Open in your browser:
   http://127.0.0.1:5000

MAIN FLOW:
- Students page: register students with roll number and name.
- Teacher page: create a subject attendance session.
- A unique QR code appears.
- Scan the QR with a phone connected to the same network if using the computer's LAN address.
- Enter the registered roll number.
- Report page shows attendance percentage.

PHONE DEMO:
For a phone to access the laptop's server, find the laptop's local IP address.
Windows: ipconfig
Linux: ip addr
Then open http://YOUR_LAPTOP_IP:5000 on the phone.
The laptop and phone should be on the same Wi-Fi.

IMPORTANT:
This is a hackathon prototype, not a production attendance/security system.
For a stronger final version, add authentication, HTTPS, rotating QR tokens, location verification,
CSV/PDF export, and proper role-based access.
