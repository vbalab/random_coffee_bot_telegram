import logging
import secrets
from email.message import EmailMessage

import aiosmtplib
from aiosmtplib import SMTPAuthenticationError

from nespresso.core.configs.settings import settings

_EMAIL_ADDRESS = settings.EMAIL_ADDRESS.get_secret_value()
_EMAIL_PASSWORD = settings.EMAIL_PASSWORD.get_secret_value()


_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


def _MaskEmail(email: str) -> str:
    """
    Mask an email's local-part for logging: ``john@nes.ru`` -> ``j***@nes.ru``.

    Logs are DM'd to admins and retained for years, so the raw PII address must
    never be written verbatim. A fixed 3-star mask also hides the local-part length.
    """
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    first = local[0] if local else ""
    return f"{first}***@{domain}"


def CreateCode() -> int:
    return secrets.randbelow(900000) + 100000


async def SendCode(email: str, code: int) -> None:
    message = EmailMessage()

    message["Subject"] = "Verification code (NESpresso)"
    message["From"] = _EMAIL_ADDRESS
    message["To"] = email
    message.set_content(
        f"Hello,\n\nThank you for registering with the NESpresso Telegram bot!\nTo complete your registration, please use the verification code below:\n\nVerification Code: {code}\n\nIf you did not initiate this request, please disregard this email.\n\nBest regards,\nThe NESpresso Bot Team"
    )

    await aiosmtplib.send(
        message,
        username=_EMAIL_ADDRESS,
        password=_EMAIL_PASSWORD,
        hostname=_SMTP_HOST,
        port=_SMTP_PORT,
        start_tls=True,
    )

    # Never log the plaintext code (it is a live secret) and mask the PII email:
    # bot.log is DM'd to all admins and retained for years.
    logging.info(f"Verification code sent to '{_MaskEmail(email)}'.")


async def TestEmail() -> None:
    logging.info("### Checking emails ... ###")

    try:
        message = EmailMessage()
        message["Subject"] = "Проверка работоспособности (NEScafeBot)"
        message["From"] = _EMAIL_ADDRESS
        message["To"] = "vbalabaev@nes.ru"
        message.set_content("Почта работает.")

        await aiosmtplib.send(
            message,
            username=_EMAIL_ADDRESS,
            password=_EMAIL_PASSWORD,
            hostname=_SMTP_HOST,
            port=_SMTP_PORT,
            start_tls=True,
        )

    except SMTPAuthenticationError as e:
        logging.error(e)
        logging.warning(
            f"process='email test' !! Email \"{_EMAIL_ADDRESS}\" is not working "
            "(authentication failed)."
        )
    except (TimeoutError, aiosmtplib.SMTPException, OSError) as e:
        # A transient SMTP/network blip (connect error, timeout, DNS failure) must
        # NOT crash startup before polling — TestEmail is log-only / non-fatal by
        # contract. Only credential errors are actionable; the rest just warn.
        logging.error(e)
        logging.warning(
            f"process='email test' !! Email \"{_EMAIL_ADDRESS}\" check failed "
            f"transiently ({type(e).__name__}); continuing startup."
        )

    logging.info("### Emails have been checked! ###")
