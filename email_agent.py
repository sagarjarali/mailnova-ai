import os
import json
import sqlite3
import base64
from datetime import datetime, timedelta

import requests
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from google import genai

load_dotenv()

app = Flask(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
DB_NAME = "email_history.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiver_email TEXT,
            subject TEXT,
            body TEXT,
            sent_time TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def parse_json_response(text: str):
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


def send_email_via_sendgrid(to_email: str, subject: str, body: str, attachment=None):
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
    MAIL_FROM = os.getenv("MAIL_FROM")

    if not SENDGRID_API_KEY:
        raise RuntimeError("SENDGRID_API_KEY is missing in Render Environment Variables.")
    if not MAIL_FROM:
        raise RuntimeError("MAIL_FROM is missing (must be a verified sender in SendGrid).")

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": MAIL_FROM},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }

    if attachment and getattr(attachment, "filename", ""):
        attachment.seek(0)
        file_bytes = attachment.read()
        payload["attachments"] = [{
            "content": base64.b64encode(file_bytes).decode("utf-8"),
            "type": "application/octet-stream",
            "filename": attachment.filename,
            "disposition": "attachment",
        }]

    res = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}"},
        json=payload,
        timeout=30,
    )

    if res.status_code != 202:
        try:
            detail = res.json()
        except Exception:
            detail = res.text
        raise RuntimeError(f"SendGrid failed ({res.status_code}): {detail}")

    # Save to DB
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO emails (receiver_email, subject, body, sent_time)
        VALUES (?, ?, ?, ?)
    """, (to_email, subject, body, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/generate-email", methods=["POST"])
def generate_email():
    try:
        if not client:
            return jsonify({"error": "GEMINI_API_KEY not set on server."}), 500

        receiver_name = request.form.get("receiver_name", "").strip()
        sender_name = request.form.get("sender_name", "").strip()
        mail_body = request.form.get("mail_body", "").strip()
        tone = request.form.get("tone", "").strip()

        tomorrow = datetime.now() + timedelta(days=1)
        formatted_date = tomorrow.strftime("%d %B %Y")

        prompt = f"""
Write a professional email.

Tone: {tone}
Replace any word like tomorrow with {formatted_date}.
No placeholders.
Return strictly valid JSON.

{{
  "subject": "email subject",
  "body": "email body"
}}

Sender: {sender_name}
Receiver: {receiver_name}
Purpose: {mail_body}
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )

        email_content = parse_json_response(response.text)
        return jsonify(email_content), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/confirm-send", methods=["POST"])
def confirm_send():
    try:
        receiver_email = request.form.get("receiver_email", "").strip()
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        attachment = request.files.get("attachment")

        if not receiver_email or not subject or not body:
            return jsonify({"error": "Missing required fields (receiver_email/subject/body)."}), 400

        send_email_via_sendgrid(receiver_email, subject, body, attachment)
        return jsonify({"message": "Email sent successfully!"}), 200

    except Exception as e:
        return jsonify({"error": f"Send failed: {str(e)}"}), 500


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