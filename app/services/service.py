import os
import re
import requests

IMGBB_TOKEN_TIMEOUT = int(os.getenv("IMGBB_TOKEN_TIMEOUT", "30"))


def UploadImageKey() -> str | None:
    html = requests.get("https://imgbb.com/", timeout=IMGBB_TOKEN_TIMEOUT).text
    match = re.search(
        r'PF\.obj\.config\.auth_token\s*=\s*"([^"]+)"',
        html
    )
    return match.group(1) if match else None
