from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File
import os
import uuid
import requests
import time
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import List, Dict, Any, Optional
from app.services.service import UploadImageKey
from app.auth_utils import get_current_user_row
from app.controllers._helpers import assemble_children

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/ProfileController", tags=["Profile"])

# Upload config (env-overridable; defaults preserve prior behavior)
IMGBB_TIMEOUT = int(os.getenv("IMGBB_TIMEOUT", "60"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))


def get_current_user(request: Request):
    return get_current_user_row(request, supabase)


@router.get("/getProfile")
def get_profile(user: dict = Depends(get_current_user)):
    try:
        person = supabase.table("people").select(
            "*, "
            "people_highlights(highlight), "
            "people_tags(tag), "
            "people_sections(id, title, people_section_items(item)), "
            "people_work_experience(company, role, duration, description), "
            "people_projects(name, url, description)"
        ).eq("id", user["id"]).single().execute()

        if not person.data:
            raise HTTPException(status_code=404, detail="Profile not found")

        p = person.data

        highlights, tags, sections = assemble_children(p, "people")

        return {
            "id": p["id"],
            "kind": p.get("kind", "people"),
            "headline": p.get("headline"),
            "subheadline": p.get("subheadline"),
            "organization": p.get("organization"),
            "location": p.get("location"),
            "experience": p.get("experience"),
            "salary": p.get("salary"),
            "intro": p.get("intro"),
            "photo": p.get("photo"),
            "resume": p.get("resume_url"),
            "resumeFilename": p.get("resume_filename"),
            "companyId": p.get("companyid"),
            "highlights": highlights,
            "tags": tags,
            "sections": sections,
            "workExperience": [
                {
                    "company": we.get("company"),
                    "role": we.get("role"),
                    "duration": we.get("duration"),
                    "description": we.get("description"),
                }
                for we in (p.get("people_work_experience") or [])
            ],
            "projects": [
                {
                    "name": proj.get("name"),
                    "url": proj.get("url"),
                    "description": proj.get("description"),
                }
                for proj in (p.get("people_projects") or [])
            ],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get_profile: {type(e).__name__}: {e}")


RESUME_STORAGE_BUCKET = "files"
RESUME_ALLOWED_EXTENSIONS = {".pdf", ".docx"}
RESUME_PUBLIC_URL_MARKER = f"/storage/v1/object/public/{RESUME_STORAGE_BUCKET}/"


def _resume_storage_path_from_url(url: Optional[str]) -> Optional[str]:
    if not url or RESUME_PUBLIC_URL_MARKER not in url:
        return None
    return url.split(RESUME_PUBLIC_URL_MARKER, 1)[1]


@router.post("/updateProfile")
def update_profile(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    try:
        person_id = user["id"]

        # If the resume file is being replaced/removed, we need the previous
        # URL so the old object can be deleted from storage below.
        existing_person = supabase.table("people").select("resume_url") \
            .eq("id", person_id).maybe_single().execute()
        old_resume_url = existing_person.data.get("resume_url") if existing_person and existing_person.data else None
        # Default to the existing value when the field is omitted entirely, so
        # an unrelated save doesn't get misread as "the resume was cleared".
        new_resume_url = payload.get("resume", old_resume_url)

        # Update scalar fields on the people row
        scalar_fields = {
            "headline": payload.get("headline"),
            "subheadline": payload.get("subheadline"),
            "organization": payload.get("organization"),
            "location": payload.get("location"),
            "experience": payload.get("experience"),
            "salary": payload.get("salary"),
            "intro": payload.get("intro"),
            "photo": payload.get("photo"),
            "resume_url": new_resume_url,
            "resume_filename": payload.get("resumeFilename"),
        }
        scalar_fields = {k: v for k, v in scalar_fields.items() if v is not None}

        if scalar_fields:
            supabase.table("people").update(scalar_fields).eq("id", person_id).execute()

        # Clean up the old resume file once the profile has been saved successfully
        if old_resume_url and old_resume_url != new_resume_url:
            old_path = _resume_storage_path_from_url(old_resume_url)
            if old_path:
                try:
                    supabase.storage.from_(RESUME_STORAGE_BUCKET).remove([old_path])
                except Exception:
                    pass  # best-effort cleanup — a stray orphaned file isn't worth failing the save

        # Replace highlights
        supabase.table("people_highlights").delete().eq("person_id", person_id).execute()
        highlights = payload.get("highlights") or []
        if highlights:
            supabase.table("people_highlights").insert([
                {"person_id": person_id, "highlight": h} for h in highlights
            ]).execute()

        # Replace tags
        supabase.table("people_tags").delete().eq("person_id", person_id).execute()
        tags = payload.get("tags") or []
        if tags:
            supabase.table("people_tags").insert([
                {"person_id": person_id, "tag": t} for t in tags
            ]).execute()

        # Replace sections + items
        existing_sections = supabase.table("people_sections").select("id").eq("person_id", person_id).execute()
        existing_section_ids = [sec["id"] for sec in (existing_sections.data or [])]
        if existing_section_ids:
            supabase.table("people_section_items").delete().in_("section_id", existing_section_ids).execute()
        supabase.table("people_sections").delete().eq("person_id", person_id).execute()

        sections = payload.get("sections") or []
        if sections:
            inserted_sections = supabase.table("people_sections").insert([
                {"person_id": person_id, "title": section.get("title")} for section in sections
            ]).execute()
            section_items = [
                {"section_id": row["id"], "item": item}
                for section, row in zip(sections, inserted_sections.data or [])
                for item in (section.get("items") or [])
            ]
            if section_items:
                supabase.table("people_section_items").insert(section_items).execute()

        # Replace work experience
        supabase.table("people_work_experience").delete().eq("person_id", person_id).execute()
        work_experience = payload.get("workExperience") or []
        if work_experience:
            supabase.table("people_work_experience").insert([
                {
                    "person_id": person_id,
                    "company": we.get("company"),
                    "role": we.get("role"),
                    "duration": we.get("duration"),
                    "description": we.get("description"),
                }
                for we in work_experience
            ]).execute()

        # Replace projects
        supabase.table("people_projects").delete().eq("person_id", person_id).execute()
        projects = payload.get("projects") or []
        if projects:
            supabase.table("people_projects").insert([
                {
                    "person_id": person_id,
                    "name": proj.get("name"),
                    "url": proj.get("url"),
                    "description": proj.get("description"),
                }
                for proj in projects
            ]).execute()

        return {"message": "Profile updated successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"update_profile: {type(e).__name__}: {e}")


@router.post("/uploadImage")
async def upload_image(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    try:
        auth_token = UploadImageKey()
        if not auth_token:
            raise HTTPException(status_code=500, detail="Failed to get upload auth token")

        contents = await file.read()

        name, ext = os.path.splitext(file.filename)
        safe_filename = f"{name}_{uuid.uuid4().hex}{ext}"

        timestamp = str(int(time.time() * 1000))

        response = requests.post(
            "https://imgbb.com/json",
            data={
                "type": "file",
                "action": "upload",
                "auth_token": auth_token,
                "timestamp": timestamp,
            },
            files={"source": (safe_filename, contents, file.content_type)},
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            },
            timeout=IMGBB_TIMEOUT,
        )

        if response.status_code != 200:
            raise HTTPException(status_code=502, detail="Image upload failed")

        data = response.json()

        if data.get("status_code") != 200:
            raise HTTPException(status_code=502, detail=data.get("error", {}).get("message", "Upload failed"))

        return {"url": data["image"]["url"]}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"upload_image: {type(e).__name__}: {e}")


@router.post("/uploadResume")
async def upload_resume(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    person_id = user["id"]

    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in RESUME_ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF or DOCX files are allowed")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File must be under 10MB")

    content_type = file.content_type or (
        "application/pdf" if ext == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    storage_path = f"resumes/{person_id}/{uuid.uuid4().hex}{ext}"

    try:
        supabase.storage.from_(RESUME_STORAGE_BUCKET).upload(
            storage_path, contents, {"content-type": content_type}
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"upload_resume: storage upload failed: {e}")

    public_url = supabase.storage.from_(RESUME_STORAGE_BUCKET).get_public_url(storage_path)
    return {"url": public_url, "filename": file.filename}


@router.post("/deleteResume")
def delete_resume(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    # For cleaning up a freshly-uploaded resume that was discarded before the
    # profile was ever saved (e.g. uploaded, then replaced or removed before
    # hitting Save). updateProfile handles deleting the *previous* file on a
    # real save — this is only for files that never made it into a save at all.
    person_id = user["id"]

    url = payload.get("url")
    path = _resume_storage_path_from_url(url)
    if not path:
        return {"success": True}

    # Scope deletion to this person's own folder so one user can't be tricked
    # into deleting another's file via this endpoint.
    if not path.startswith(f"resumes/{person_id}/"):
        raise HTTPException(status_code=403, detail="Not allowed")

    try:
        supabase.storage.from_(RESUME_STORAGE_BUCKET).remove([path])
    except Exception:
        pass  # best-effort cleanup

    return {"success": True}
