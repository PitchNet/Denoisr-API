import os

from dotenv import load_dotenv
from fastapi import HTTPException, Request, Response, status
from jose import JWTError, jwt
from supabase import Client

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10080  # 7 days

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
