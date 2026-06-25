from fastapi import APIRouter, HTTPException, Depends, Request
import os
import json
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import Dict, Any
from pywebpush import webpush, WebPushException
from app.auth_utils import get_current_user_row

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_CLAIM_EMAIL = os.getenv("VAPID_CLAIM_EMAIL", "notifications@denoisr.com")
PUSH_TTL_SECONDS = int(os.getenv("PUSH_TTL_SECONDS", "86400"))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/NotificationController", tags=["Notifications"])


def get_current_user(request: Request):
    return get_current_user_row(request, supabase)


def send_push(user_id: str, title: str, body: str, data: Dict[str, Any] = None):
    """Send a push notification to all devices of a user and persist in-app notification."""
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        print("[send_push] VAPID keys not configured")
        return

    # Check notification preferences before doing anything
    notif_type = (data or {}).get("type", "general")
    try:
        pref_res = supabase.table("people").select(
            "notify_connections, notify_messages, notify_job_updates"
        ).eq("id", user_id).single().execute()
        if pref_res.data:
            prefs = pref_res.data
            if notif_type == "connection" and not prefs.get("notify_connections", True):
                return
            if notif_type == "message" and not prefs.get("notify_messages", True):
                return
            if notif_type == "job_status" and not prefs.get("notify_job_updates", True):
                return
    except Exception as e:
        print(f"[send_push] Failed to check notification prefs: {e}")

    # Persist in-app notification
    notif_data = data or {}
    try:
        supabase.table("notifications").insert({
            "user_id": user_id,
            "type": notif_data.get("type", "general"),
            "title": title,
            "body": body,
            "data": notif_data,
        }).execute()
    except Exception as e:
        print(f"[send_push] Failed to persist notification: {e}")

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
                ttl=PUSH_TTL_SECONDS,
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


@router.get("/getNotifications")
def get_notifications(cursor: str = None, limit: int = 20, user: dict = Depends(get_current_user)):
    query = supabase.table("notifications").select("*") \
        .eq("user_id", user["id"]) \
        .order("created_at", desc=True) \
        .limit(limit)

    if cursor:
        c = supabase.table("notifications").select("created_at").eq("id", cursor).single().execute()
        if c.data:
            query = query.lt("created_at", c.data["created_at"])

    result = query.execute()
    items = result.data or []
    has_more = len(items) == limit
    next_cursor = items[-1]["id"] if has_more else None

    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@router.post("/markRead")
def mark_read(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    ids = payload.get("ids")
    if ids:
        supabase.table("notifications").update({"read": True}) \
            .in_("id", ids) \
            .eq("user_id", user["id"]) \
            .execute()
    else:
        supabase.table("notifications").update({"read": True}) \
            .eq("user_id", user["id"]) \
            .eq("read", False) \
            .execute()
    return {"message": "Marked as read"}


@router.get("/unreadCount")
def unread_count(user: dict = Depends(get_current_user)):
    result = supabase.table("notifications").select("id") \
        .eq("user_id", user["id"]) \
        .eq("read", False) \
        .execute()
    return {"count": len(result.data or [])}
