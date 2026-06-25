import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import HTTPException, Request, Response, status
from jose import JWTError, jwt
from supabase import Client

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10080  # 7 days

RESET_TOKEN_PURPOSE = "password_reset"
RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "30"))

AUTH_COOKIE_NAME = "denoisr_auth_token"

# Cross-site (denoisr-ui.vercel.app -> denoisr-api.onrender.com) cookies need
# SameSite=None + Secure. Override via env for local HTTP dev, e.g.
# COOKIE_SECURE=false COOKIE_SAMESITE=lax when UI and API share a scheme+host
# (see Denoisr-UI CLAUDE.md).
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "none")


def set_auth_cookie(response: Response, token: str) -> None:
    """Issue the session JWT as an httpOnly cookie — never returned in a JSON body, never readable by page JS."""
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )


def extract_token(request: Request) -> str:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[len("Bearer "):]
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return token


def decode_subject(request: Request) -> str:
    token = extract_token(request)
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token: subject missing")
    return subject


def get_current_user_row(request: Request, supabase: Client) -> dict:
    subject = decode_subject(request)
    user = supabase.table("people").select("*").eq("id", subject).single().execute()
    if not user.data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user.data


def get_optional_user_row(request: Request, supabase: Client) -> dict | None:
    """Like get_current_user_row, but returns None instead of raising when
    there's no valid session — for endpoints that are public but personalize
    their response when a session does exist."""
    try:
        return get_current_user_row(request, supabase)
    except HTTPException:
        return None


def is_admin(user: dict) -> bool:
    """Crude allowlist gate: no roles table, just a comma-separated list of
    people.id values in ADMIN_USER_IDS. Good enough until there's an actual
    need for more than a couple of trusted reviewers."""
    admin_ids = {uid.strip() for uid in os.getenv("ADMIN_USER_IDS", "").split(",") if uid.strip()}
    return str(user.get("id")) in admin_ids


def create_reset_token(user_id: str, password_hash: str) -> str:
    """A short-lived, single-use password-reset token. No DB column needed:
    binding it to a fragment of the current password hash means the token
    stops verifying the moment the password actually changes, which is what
    gives it single-use semantics without a 'used' flag anywhere."""
    payload = {
        "sub": user_id,
        "purpose": RESET_TOKEN_PURPOSE,
        "pwv": (password_hash or "")[-16:],
        "exp": datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_reset_token(token: str, supabase: Client) -> dict:
    invalid = HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise invalid

    if payload.get("purpose") != RESET_TOKEN_PURPOSE or not payload.get("sub"):
        raise invalid

    user = supabase.table("people").select("*").eq("id", payload["sub"]).execute()
    if not user.data:
        raise invalid

    person = user.data[0]
    if (person.get("passwordhash") or "")[-16:] != payload.get("pwv"):
        raise invalid

    return person
