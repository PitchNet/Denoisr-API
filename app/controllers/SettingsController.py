from fastapi import APIRouter, HTTPException, Depends, Request, Response
from pydantic import BaseModel
from typing import Literal
from datetime import datetime, timezone
import bcrypt
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from app.auth_utils import get_current_user_row, clear_auth_cookie

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


class DeleteAccountRequest(BaseModel):
    password: str


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


@router.get("/exportData")
def export_data(user: dict = Depends(get_current_user)):
    """Everything Denoisr holds about the current user, as one JSON document."""
    person_id = user["id"]

    profile = dict(user)
    profile.pop("passwordhash", None)

    highlights = supabase.table("people_highlights").select("highlight").eq("person_id", person_id).execute()
    tags = supabase.table("people_tags").select("tag").eq("person_id", person_id).execute()

    sections_res = supabase.table("people_sections").select(
        "id, title, people_section_items(item)"
    ).eq("person_id", person_id).execute()
    sections = [
        {"title": sec["title"], "items": [i["item"] for i in (sec.get("people_section_items") or [])]}
        for sec in (sections_res.data or [])
    ]

    work_experience = supabase.table("people_work_experience") \
        .select("company, role, duration, description").eq("person_id", person_id).execute()
    projects = supabase.table("people_projects") \
        .select("name, url, description").eq("person_id", person_id).execute()

    job_actions = supabase.table("user_job_actions") \
        .select("job_id, action, status, created_at").eq("user_id", person_id).execute()
    people_actions = supabase.table("user_people_actions") \
        .select("people_id, action, created_at").eq("user_id", person_id).execute()

    sent_messages = supabase.table("messages") \
        .select("conversation_id, content, created_at").eq("sender_id", person_id).execute()

    notifications = supabase.table("notifications") \
        .select("type, title, body, created_at, read").eq("user_id", person_id).execute()

    return {
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "highlights": [h["highlight"] for h in (highlights.data or [])],
        "tags": [t["tag"] for t in (tags.data or [])],
        "sections": sections,
        "workExperience": work_experience.data or [],
        "projects": projects.data or [],
        "jobActions": job_actions.data or [],
        "peopleActions": people_actions.data or [],
        "sentMessages": sent_messages.data or [],
        "notifications": notifications.data or [],
    }


@router.post("/deleteAccount")
def delete_account(request: DeleteAccountRequest, response: Response, user: dict = Depends(get_current_user)):
    if not bcrypt.checkpw(request.password.encode(), user["passwordhash"].encode()):
        raise HTTPException(status_code=400, detail="Password is incorrect")

    person_id = user["id"]

    # Children before parent — no guaranteed FK cascade in this schema, so
    # delete in dependency order. Posted companies/jobs are deliberately left
    # alone: they can be shared business data (other applicants, teammates),
    # not solely this account's personal data.
    supabase.table("message_reactions").delete().eq("user_id", person_id).execute()
    supabase.table("messages").delete().eq("sender_id", person_id).execute()
    supabase.table("conversation_participants").delete().eq("user_id", person_id).execute()
    supabase.table("user_job_actions").delete().eq("user_id", person_id).execute()
    supabase.table("user_people_actions").delete().eq("user_id", person_id).execute()
    supabase.table("user_people_actions").delete().eq("people_id", person_id).execute()
    supabase.table("blocked_users").delete().eq("blocker_id", person_id).execute()
    supabase.table("blocked_users").delete().eq("blocked_id", person_id).execute()
    supabase.table("user_reports").delete().eq("reporter_id", person_id).execute()
    supabase.table("user_reports").delete().eq("reported_id", person_id).execute()
    supabase.table("notifications").delete().eq("user_id", person_id).execute()
    supabase.table("push_subscriptions").delete().eq("user_id", person_id).execute()

    sections = supabase.table("people_sections").select("id").eq("person_id", person_id).execute()
    section_ids = [sec["id"] for sec in (sections.data or [])]
    if section_ids:
        supabase.table("people_section_items").delete().in_("section_id", section_ids).execute()
    supabase.table("people_sections").delete().eq("person_id", person_id).execute()
    supabase.table("people_highlights").delete().eq("person_id", person_id).execute()
    supabase.table("people_tags").delete().eq("person_id", person_id).execute()
    supabase.table("people_work_experience").delete().eq("person_id", person_id).execute()
    supabase.table("people_projects").delete().eq("person_id", person_id).execute()

    supabase.table("people").delete().eq("id", person_id).execute()

    clear_auth_cookie(response)
    return {"message": "Account deleted"}
