import os
import sqlite3
import smtplib
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

from groq import Groq

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# ==============================
# LOAD ENV
# ==============================
load_dotenv()

app = Flask(__name__)

DB_NAME = "email_history.db"

# ==============================
# GROQ CLIENT
# ==============================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(
    api_key=GROQ_API_KEY
)

# ==============================
# DATABASE INIT
# ==============================
def init_db():

    conn = sqlite3.connect(DB_NAME)

    cur = conn.cursor()

    cur.execute("""
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

# ==============================
# SAVE HISTORY
# ==============================
def save_to_db(to_email, subject, body):

    conn = sqlite3.connect(DB_NAME)

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO emails
        (receiver_email, subject, body, sent_time)
        VALUES (?, ?, ?, ?)
    """, (
        to_email,
        subject,
        body,
        datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    ))

    conn.commit()
    conn.close()

# ==============================
# SEND EMAIL
# ==============================
def send_email(receiver_email, subject, body, attachment=None):

    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")

    print("===================================")
    print("EMAIL:", repr(gmail_user))
    print("RECEIVER:", repr(receiver_email))
    print("===================================")

    msg = MIMEMultipart()

    msg["From"] = gmail_user
    msg["To"] = receiver_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    # ==============================
    # ATTACHMENT
    # ==============================
    if attachment and attachment.filename != "":

        attachment.seek(0)

        part = MIMEBase("application", "octet-stream")

        part.set_payload(attachment.read())

        encoders.encode_base64(part)

        part.add_header(
            "Content-Disposition",
            f"attachment; filename={attachment.filename}"
        )

        msg.attach(part)

    # ==============================
    # SMTP
    # ==============================
    server = smtplib.SMTP("smtp.gmail.com", 587)

    server.starttls()

    server.login(gmail_user, gmail_password)

    # FIXED SEND METHOD
    server.sendmail(
        gmail_user,
        receiver_email,
        msg.as_string()
    )

    server.quit()

# ==============================
# HOME
# ==============================
@app.route("/")
def home():
    return render_template("index.html")

# ==============================
# OPTIONAL PING ROUTE
# ==============================
@app.route("/ping")
def ping():
    return "Server Active"

# ==============================
# GENERATE EMAIL
# ==============================
@app.route("/generate-email", methods=["POST"])
def generate_email():

    try:

        receiver_name = request.form.get("receiver_name")

        sender_name = request.form.get("sender_name")

        mail_body = request.form.get("mail_body")

        tone = request.form.get("tone")

        email_type = request.form.get("email_type")

        tomorrow = datetime.now() + timedelta(days=1)

        formatted_date = tomorrow.strftime("%d %B %Y")

        prompt = f"""
Write a professional ready-to-send email.

Rules:
- No placeholders
- No markdown
- Replace words like tomorrow with exact date: {formatted_date}
- Proper formatting
- Professional structure

Tone: {tone}
Email Type: {email_type}

Sender Name: {sender_name}
Receiver Name: {receiver_name}

Purpose:
{mail_body}

Return response in this exact format:

SUBJECT: your subject here

BODY:
your email body here
"""

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7
        )

        response_text = completion.choices[0].message.content

        # CLEAN RESPONSE
        response_text = response_text.replace("```", "").strip()

        print("AI RESPONSE:")
        print(response_text)

        # ==============================
        # PARSE SUBJECT & BODY
        # ==============================
        subject = ""
        body = ""

        if "SUBJECT:" in response_text and "BODY:" in response_text:

            parts = response_text.split("BODY:")

            subject_part = parts[0]
            body_part = parts[1]

            subject = subject_part.replace("SUBJECT:", "").strip()

            body = body_part.strip()

        else:
            return jsonify({
                "error": "AI response format invalid"
            }), 500

        return jsonify({
            "subject": subject,
            "body": body
        })

    except Exception as e:

        import traceback
        traceback.print_exc()

        return jsonify({
            "error": str(e)
        }), 500

# ==============================
# CONFIRM & SEND
# ==============================
@app.route("/confirm-send", methods=["POST"])
def confirm_send():

    try:

        receiver_email = request.form.get("receiver_email")

        subject = request.form.get("subject")

        body = request.form.get("body")

        attachment = request.files.get("attachment")

        print("RECEIVER =", receiver_email)

        send_email(
            receiver_email,
            subject,
            body,
            attachment
        )

        save_to_db(
            receiver_email,
            subject,
            body
        )

        return jsonify({
            "message": "Email sent successfully"
        })

    except Exception as e:

        import traceback
        traceback.print_exc()

        return jsonify({
            "error": str(e)
        }), 500

# ==============================
# HISTORY
# ==============================
@app.route("/history")
def history():

    conn = sqlite3.connect(DB_NAME)

    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM emails
        ORDER BY id DESC
    """)

    emails = cur.fetchall()

    conn.close()

    return render_template(
        "history.html",
        emails=emails
    )

# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    app.run(debug=True)