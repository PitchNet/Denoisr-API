from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os
import json
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import Dict, Any
from pywebpush import webpush, WebPushException

load_dotenv()
security = HTTPBearer()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "notifications@denoisr.com")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/NotificationController", tags=["Notifications"])

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM = "HS256"


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject = payload.get("sub")
        if not subject:
            raise HTTPException(status_code=401, detail="Invalid token: subject missing")
        user = supabase.table("people").select("*").eq("id", subject).single().execute()
        if not user.data:
            user = supabase.table("people").select("*").eq("id", subject).single().execute()
        if not user.data:
            raise HTTPException(status_code=401, detail="User not found")
        return user.data
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def send_push(user_id: str, title: str, body: str, data: Dict[str, Any] = None):
    """Send a push notification to all devices of a user."""
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        print("[send_push] VAPID keys not configured")
        return

    subs = supabase.table("push_subscriptions") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()

    if not subs.data:
        print(f"[send_push] No subscriptions for user {user_id}")
        return

    print(f"[send_push] Sending to {len(subs.data)} device(s) for user {user_id}")

    payload = {"title": title, "body": body, "data": data or {}}
    payload_bytes = json.dumps(payload).encode("utf-8")

    expired = []
    for sub in subs.data:
        try:
            resp = webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {
                        "p256dh": sub["p256dh_key"],
                        "auth": sub["auth_key"],
                    },
                },
                data=payload_bytes,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
                ttl=86400,
                verbose=True,
            )
            print(f"[send_push] Push response: {resp.status_code}")
            if resp.status_code == 410:
                expired.append(sub["id"])
        except WebPushException as e:
            print(f"[send_push] WebPushException: {e}")
            if e.response:
                if e.response.status_code in (410, 404):
                    expired.append(sub["id"])
        except Exception as e:
            print(f"[send_push] Unexpected error: {e}")

    if expired:
        print(f"[send_push] Cleaning {len(expired)} expired subscription(s)")
        supabase.table("push_subscriptions") \
            .delete() \
            .in_("id", expired) \
            .execute()


@router.post("/subscribe")
def subscribe(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    endpoint = payload.get("endpoint")
    p256dh = payload.get("p256dh")
    auth = payload.get("auth")

    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="endpoint, p256dh, and auth required")

    supabase.table("push_subscriptions").upsert(
        {
            "user_id": user["id"],
            "endpoint": endpoint,
            "p256dh_key": p256dh,
            "auth_key": auth,
        },
        on_conflict="user_id,endpoint"
    ).execute()

    return {"message": "Subscribed"}


@router.post("/unsubscribe")
def unsubscribe(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    endpoint = payload.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint required")

    supabase.table("push_subscriptions") \
        .delete() \
        .eq("user_id", user["id"]) \
        .eq("endpoint", endpoint) \
        .execute()

    return {"message": "Unsubscribed"}


@router.get("/vapidPublicKey")
def vapid_public_key():
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=500, detail="VAPID public key not configured")
    return {"publicKey": VAPID_PUBLIC_KEY}


@router.post("/testPush")
def test_push(user: dict = Depends(get_current_user)):
    send_push(
        user["id"],
        "Test notification",
        "If you see this, push notifications are working!",
        {"type": "test"},
    )
    return {"message": "Test push sent"}
