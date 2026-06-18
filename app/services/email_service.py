import os
import requests

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "Denoisr <onboarding@resend.dev>")


def send_password_reset_email(to_email: str, reset_link: str) -> bool:
    """Send the password-reset email via Resend. Returns True on success, False
    on any delivery failure so the caller can fall back to an inline token."""
    if not RESEND_API_KEY:
        print(f"[email_service] RESEND_API_KEY not set — password reset link for {to_email}: {reset_link}")
        return True

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
            return False

        return True
    except requests.RequestException as e:
        print(f"[email_service] Failed to send password reset email: {type(e).__name__}: {e}")
        return False
