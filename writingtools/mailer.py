"""Send the daily spark via SMTP. Reads config from environment variables."""
import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send(html: str) -> None:
    """Send the spark email. Required env vars:
      EMAIL_SMTP_HOST, EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO
    """
    smtp_host = os.environ["EMAIL_SMTP_HOST"]
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
    smtp_user = os.environ["EMAIL_SMTP_USER"]
    smtp_pass = os.environ["EMAIL_SMTP_PASSWORD"]
    from_addr = os.environ["EMAIL_FROM"]
    to_addr   = os.environ["EMAIL_TO"]

    today = date.today().strftime("%A, %B %-d")
    subject = f"✦ Daily Writing Spark — {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = to_addr
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_addr, [to_addr], msg.as_string())

    print(f"Sent: {subject} → {to_addr}")
