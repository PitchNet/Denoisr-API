import re
import requests


def UploadImageKey() -> str | None:
    html = requests.get("https://imgbb.com/", timeout=30).text
    match = re.search(
        r'PF\.obj\.config\.auth_token\s*=\s*"([^"]+)"',
        html
    )
    return match.group(1) if match else None
