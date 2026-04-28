"""
Email tools:
  write_email  – LLM-powered email drafter (no SMTP, safe to run anytime)
  send_email   – actually sends via SMTP         ⚠ REQUIRES APPROVAL
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from app.agent.llm_client import call_llm
from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

EMAIL_WRITER_SYSTEM = """\
You are a professional business writer. Draft a polished email based on the
brief. Output only the email content (no JSON wrapper, no meta-commentary):

Subject: <subject line>

<email body with proper greeting, paragraphs, and sign-off>
"""


async def write_email(
    to: str,
    subject_brief: str,
    body_brief: str,
    tone: str = "professional",
    sender_name: str = "ClaudBot",
) -> str:
    """
    Draft an email using the LLM.

    Args:
        to:            Recipient email address (informational, not sent).
        subject_brief: One-line description of the subject.
        body_brief:    Key points to include in the body.
        tone:          professional | friendly | formal | casual.
        sender_name:   Name to sign the email with.

    Returns:
        Formatted email as plain text (Subject line + body).
    """
    log.info("write_email", to=to, tone=tone)

    prompt = f"""\
To: {to}
Subject brief: {subject_brief}
Body brief: {body_brief}
Tone: {tone}
Sign off as: {sender_name}

Draft the email now.
"""

    content = await call_llm(
        [
            {"role": "system", "content": EMAIL_WRITER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )

    return content.strip()


async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
) -> str:
    """
    Send an email via SMTP.  ⚠ This tool requires approval before execution.

    Args:
        to:      Recipient address (comma-separated for multiple).
        subject: Email subject line.
        body:    Plain-text email body.
        cc:      Optional CC addresses.

    Returns:
        Confirmation string.
    """
    log.info("send_email", to=to, subject=subject[:60])

    if not settings.smtp_user or not settings.smtp_password:
        raise RuntimeError(
            "SMTP credentials not configured. Set SMTP_USER and SMTP_PASSWORD."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"ClaudBot <{settings.email_from or settings.smtp_user}>"
    msg["To"] = to
    if cc:
        msg["Cc"] = cc

    msg.attach(MIMEText(body, "plain"))

    recipients = [r.strip() for r in to.split(",")]
    if cc:
        recipients += [r.strip() for r in cc.split(",")]

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(
                settings.email_from or settings.smtp_user,
                recipients,
                msg.as_string(),
            )
    except Exception as exc:
        log.error("send_email_failed", error=str(exc))
        raise

    log.info("email_sent", to=to, recipients=len(recipients))
    return f"Email sent successfully to {to}."
