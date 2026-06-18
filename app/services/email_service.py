import os
import requests

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "Denoisr <onboarding@resend.dev>")


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    """Send the password-reset email via Resend.

    Swallows delivery failures (just logs them) rather than raising: the
    caller always returns the same generic response regardless of whether
    the address is registered or the email actually went out, so a
    transient provider outage doesn't turn into an account-enumeration
    signal or a 500.
    """
    if not RESEND_API_KEY:
        print(f"[email_service] RESEND_API_KEY not set — password reset link for {to_email}: {reset_link}")
        return

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={
                "from": RESEND_FROM_EMAIL,
                "to": [to_email],
                "subject": "Reset your Denoisr password",
                "html": (
                    "<p>Someone requested a password reset for this email on Denoisr.</p>"
                    f"<p><a href=\"{reset_link}\">Reset your password</a> — this link expires in 30 minutes.</p>"
                    "<p>If you didn't request this, you can safely ignore this email.</p>"
                ),
            },
            timeout=10,
        )
        if response.status_code >= 400:
            print(f"[email_service] Resend API error {response.status_code}: {response.text}")
    except requests.RequestException as e:
        print(f"[email_service] Failed to send password reset email: {type(e).__name__}: {e}")
