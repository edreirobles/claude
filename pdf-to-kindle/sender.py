"""Email delivery to a Kindle address via SMTP."""

import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Well-known SMTP presets
SMTP_PRESETS = {
    "Gmail":   {"host": "smtp.gmail.com",   "port": 587},
    "Outlook": {"host": "smtp.office365.com","port": 587},
    "Yahoo":   {"host": "smtp.mail.yahoo.com","port": 587},
    "Custom":  {"host": "",                  "port": 587},
}


def send_to_kindle(
    file_path: str,
    kindle_email: str,
    sender_email: str,
    sender_password: str,
    smtp_host: str,
    smtp_port: int = 587,
) -> None:
    """
    Send a converted file to a Kindle address via SMTP (STARTTLS).

    Raises smtplib.SMTPException or OSError on failure.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 50:
        raise ValueError(
            f"El archivo pesa {size_mb:.1f} MB. "
            "Amazon acepta hasta 50 MB por email a Kindle."
        )

    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = kindle_email
    # Subject must be non-empty; Amazon ignores it but some servers reject blank subjects
    msg["Subject"] = path.stem

    msg.attach(MIMEText("Enviado con PDF → Kindle Converter.", "plain"))

    with open(file_path, "rb") as f:
        attachment = MIMEApplication(f.read(), Name=path.name)
    attachment["Content-Disposition"] = f'attachment; filename="{path.name}"'
    msg.attach(attachment)

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, kindle_email, msg.as_string())
