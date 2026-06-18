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
                    "<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head>"
                    "<body style=\"margin:0;padding:0;background:#fbfaf6;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;\">"
                    "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\">"
                    "<tr><td align=\"center\" style=\"padding:48px 16px;\">"
                    "<table role=\"presentation\" width=\"440\" cellpadding=\"0\" cellspacing=\"0\" "
                    "style=\"background:#ffffff;border-radius:16px;\">"
                    # Wordmark
                    "<tr><td style=\"padding:40px 40px 0;text-align:center;\">"
                    "<span style=\"font-size:20px;font-weight:700;letter-spacing:-0.6px;color:#1a1715;\">"
                    "Denoisr<span style=\"color:rgba(26,23,21,0.45);\">.</span>"
                    "</span></td></tr>"
                    # Body
                    "<tr><td style=\"padding:28px 40px 8px;text-align:center;\">"
                    "<h1 style=\"margin:0 0 10px;font-size:22px;font-weight:600;letter-spacing:-0.4px;color:#1a1715;\">"
                    "Reset your password</h1>"
                    "<p style=\"margin:0;font-size:15px;line-height:1.5;color:rgba(26,23,21,0.66);\">"
                    "Someone requested a password reset for your Denoisr account. "
                    "Click the button below to set a new one."
                    "</p></td></tr>"
                    # CTA
                    "<tr><td style=\"padding:28px 40px;text-align:center;\">"
                    f"<a href=\"{reset_link}\" "
                    "style=\"display:inline-block;padding:13px 32px;border-radius:999px;background:#1a1715;"
                    "color:#ffffff;font-size:14px;font-weight:500;text-decoration:none;\">"
                    "Reset password</a></td></tr>"
                    # Expiry note
                    "<tr><td style=\"padding:0 40px 32px;text-align:center;\">"
                    "<p style=\"margin:0;font-size:13px;line-height:1.5;color:rgba(26,23,21,0.45);\">"
                    "This link expires in 30 minutes. If you didn't request this, you can safely ignore this email."
                    "</p></td></tr>"
                    # Footer
                    "<tr><td style=\"padding:20px 40px;border-top:1px solid rgba(26,23,21,0.06);text-align:center;\">"
                    "<p style=\"margin:0;font-size:12px;color:rgba(26,23,21,0.45);\">Denoisr</p>"
                    "</td></tr></table></td></tr></table></body></html>"
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
