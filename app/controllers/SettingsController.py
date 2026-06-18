from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Literal
import bcrypt
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from app.auth_utils import get_current_user_row

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/SettingsController", tags=["Settings"])


def get_current_user(request: Request):
    return get_current_user_row(request, supabase)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class NotificationPrefsRequest(BaseModel):
    notify_connections: bool
    notify_messages: bool
    notify_job_updates: bool


class PrivacySettingsRequest(BaseModel):
    profile_visible: bool
    allow_messages_from: Literal["all", "connections", "none"]


@router.get("/getSettings")
def get_settings(user: dict = Depends(get_current_user)):
    return {
        "notify_connections": user.get("notify_connections", True),
        "notify_messages": user.get("notify_messages", True),
        "notify_job_updates": user.get("notify_job_updates", True),
        "profile_visible": user.get("profile_visible", True),
        "allow_messages_from": user.get("allow_messages_from", "all"),
    }


@router.post("/changePassword")
def change_password(request: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    if not bcrypt.checkpw(request.current_password.encode(), user["passwordhash"].encode()):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if len(request.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    new_hash = bcrypt.hashpw(request.new_password.encode(), bcrypt.gensalt()).decode()
    supabase.table("people").update({"passwordhash": new_hash}).eq("id", user["id"]).execute()

    return {"message": "Password updated successfully"}


@router.post("/updateNotificationPreferences")
def update_notification_preferences(request: NotificationPrefsRequest, user: dict = Depends(get_current_user)):
    supabase.table("people").update({
        "notify_connections": request.notify_connections,
        "notify_messages": request.notify_messages,
        "notify_job_updates": request.notify_job_updates,
    }).eq("id", user["id"]).execute()

    return {"message": "Notification preferences updated"}


@router.post("/updatePrivacySettings")
def update_privacy_settings(request: PrivacySettingsRequest, user: dict = Depends(get_current_user)):
    supabase.table("people").update({
        "profile_visible": request.profile_visible,
        "allow_messages_from": request.allow_messages_from,
    }).eq("id", user["id"]).execute()

    return {"message": "Privacy settings updated"}
