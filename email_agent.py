import os
import json
import smtplib
import sqlite3
import re
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from google import genai

load_dotenv()

# ==============================
# CONFIG
# ==============================
app = Flask(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
DB_NAME = "email_history.db"


# ==============================
# DATABASE SETUP
# ==============================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiver_email TEXT,
            email_type TEXT,
            tone TEXT,
            subject TEXT,
            body TEXT,
            sent_time TEXT
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ==============================
# UTIL FUNCTIONS
# ==============================
def parse_json_response(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


def is_valid_email(email):
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return re.match(pattern, email)


def log_email(receiver_email, email_type, tone, subject, body):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO emails (receiver_email, email_type, tone, subject, body, sent_time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        receiver_email,
        email_type,
        tone,
        subject,
        body,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()


def send_email(to_email, subject, body, attachment=None):
    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    if attachment and attachment.filename:
        attachment.seek(0)
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment.filename}"',
        )
        msg.attach(part)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)


# ==============================
# ROUTES
# ==============================
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/generate-email", methods=["POST"])
def generate_email():
    try:
        receiver_name = request.form.get("receiver_name")
        sender_name = request.form.get("sender_name")
        mail_body = request.form.get("mail_body")
        tone = request.form.get("tone")
        email_type = request.form.get("email_type")

        if not all([receiver_name, sender_name, mail_body, tone, email_type]):
            return jsonify({"error": "All fields are required."}), 400

        tomorrow = datetime.now() + timedelta(days=1)
        formatted_date = tomorrow.strftime("%d %B %Y")

        # Structured Prompt Architecture
        prompt = f"""
You are an AI Email Writing Assistant.

ROLE:
Professional email generator.

TASK:
Write a {email_type} email.

CONSTRAINTS:
- Tone must be {tone}
- Replace words like tomorrow with {formatted_date}
- No placeholders
- Clear subject line
- Professional closing
- Return strictly valid JSON

FORMAT:
{{
    "subject": "email subject",
    "body": "email body"
}}

DETAILS:
Sender: {sender_name}
Receiver: {receiver_name}
Purpose: {mail_body}
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )

        email_content = parse_json_response(response.text)

        return jsonify(email_content)

    except Exception as e:
        return jsonify({"error": f"Generation failed: {str(e)}"}), 500


@app.route("/confirm-send", methods=["POST"])
def confirm_send():
    try:
        receiver_email = request.form.get("receiver_email", "").strip()
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        attachment = request.files.get("attachment")

        if not receiver_email or not subject or not body:
            return jsonify({"error": "Missing required fields (receiver_email/subject/body)."}), 400

        # Extra safety checks for env vars (common Render issue)
        if not GMAIL_USER or not GMAIL_APP_PASSWORD:
            return jsonify({"error": "Server email credentials are not configured (GMAIL_USER / GMAIL_APP_PASSWORD)."}), 500

        send_email(receiver_email, subject, body, attachment)
        return jsonify({"message": "Email sent successfully!"}), 200

    except smtplib.SMTPAuthenticationError:
        return jsonify({"error": "SMTP authentication failed. Check GMAIL_USER and GMAIL_APP_PASSWORD (App Password must match this Gmail)."}), 500

    except Exception as e:
        # Always return JSON (prevents Unexpected token '<' on frontend)
        return jsonify({"error": f"Server error while sending: {str(e)}"}), 500
@app.route("/history")
def history():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM emails ORDER BY id DESC")
    emails = cursor.fetchall()
    conn.close()

    return render_template("history.html", emails=emails)


if __name__ == "__main__":
    app.run(debug=True)