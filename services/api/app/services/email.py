"""Outgoing email over SMTP (docs/CLAUDE.md §3).

In development the stack runs Mailpit and the links are also printed to the api console.
Only links and generic text are sent; nothing a child said is ever emailed.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from anyio import to_thread

from app.config import settings

logger = logging.getLogger("app.email")


def _send_blocking(message: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_starttls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


async def send_email(*, to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        await to_thread.run_sync(_send_blocking, message)
    except (OSError, smtplib.SMTPException) as error:
        # never fail the request because mail is down; the parent can ask for a new link
        logger.error("could not send %r: %s", subject, type(error).__name__)


def _link(path: str, token: str) -> str:
    return f"{settings.public_web_url.rstrip('/')}{path}?token={token}"


async def send_verification_email(*, to: str, token: str) -> None:
    link = _link("/verify", token)
    if settings.email_print_links:
        logger.info("verification link for %s: %s", to, link)
    await send_email(
        to=to,
        subject="Potvrdite svoju email adresu / Confirm your email address",
        body=(
            "Zdravo!\n\n"
            "Potvrdite svoju email adresu da biste nastavili podesavanje Bruno racuna:\n"
            f"{link}\n\n"
            f"Link vazi {settings.verify_token_hours} h.\n\n"
            "---\n\n"
            "Hello!\n\n"
            "Confirm your email address to continue setting up your Bruno account:\n"
            f"{link}\n\n"
            f"The link is valid for {settings.verify_token_hours} h.\n"
        ),
    )


async def send_password_reset_email(*, to: str, token: str) -> None:
    link = _link("/reset-password", token)
    if settings.email_print_links:
        logger.info("password reset link for %s: %s", to, link)
    await send_email(
        to=to,
        subject="Nova sifra / Password reset",
        body=(
            "Zdravo!\n\n"
            "Zatrazili ste novu sifru. Postavite je ovde:\n"
            f"{link}\n\n"
            f"Link vazi {settings.reset_token_hours} h. Ako to niste bili vi, ignorišite ovaj email.\n\n"
            "---\n\n"
            "Hello!\n\n"
            "You asked to reset your password. Set a new one here:\n"
            f"{link}\n\n"
            f"The link is valid for {settings.reset_token_hours} h. "
            "If this was not you, ignore this email.\n"
        ),
    )
