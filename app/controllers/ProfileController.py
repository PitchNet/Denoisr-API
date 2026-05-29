from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os
import requests
import time
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import List, Dict, Any
from app.services.service import UploadImageKey

load_dotenv()
security = HTTPBearer()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/ProfileController", tags=["Profile"])

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM = "HS256"


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject = payload.get("sub")

        if not subject:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: subject missing"
            )

        user = supabase.table("people").select("*").eq("id", subject).single().execute()
        if not user.data:
            user = supabase.table("people").select("*").eq("id", subject).single().execute()

        if not user.data:
            raise HTTPException(status_code=401, detail="User not found")

        return user.data

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


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

        highlights = [h["highlight"] for h in p.get("people_highlights", []) if "highlight" in h]
        tags = [t["tag"] for t in p.get("people_tags", []) if "tag" in t]

        sections_raw = p.get("people_sections", [])
        sections: List[Dict[str, Any]] = []
        for sec in sections_raw:
            items = [it["item"] for it in sec.get("people_section_items", []) if "item" in it]
            sections.append({"title": sec["title"], "items": items})

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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/updateProfile")
def update_profile(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    try:
        person_id = user["id"]

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
        }
        scalar_fields = {k: v for k, v in scalar_fields.items() if v is not None}

        if scalar_fields:
            supabase.table("people").update(scalar_fields).eq("id", person_id).execute()

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
        for sec in (existing_sections.data or []):
            supabase.table("people_section_items").delete().eq("section_id", sec["id"]).execute()
        supabase.table("people_sections").delete().eq("person_id", person_id).execute()

        sections = payload.get("sections") or []
        for section in sections:
            section_insert = supabase.table("people_sections").insert({
                "person_id": person_id, "title": section.get("title")
            }).execute()
            if section_insert.data:
                section_id = section_insert.data[0]["id"]
                items = section.get("items") or []
                if items:
                    supabase.table("people_section_items").insert([
                        {"section_id": section_id, "item": item} for item in items
                    ]).execute()

        # Replace work experience
        supabase.table("people_work_experience").delete().eq("person_id", person_id).execute()
        work_experience = payload.get("workExperience") or []
        for we in work_experience:
            supabase.table("people_work_experience").insert({
                "person_id": person_id,
                "company": we.get("company"),
                "role": we.get("role"),
                "duration": we.get("duration"),
                "description": we.get("description"),
            }).execute()

        # Replace projects
        supabase.table("people_projects").delete().eq("person_id", person_id).execute()
        projects = payload.get("projects") or []
        for proj in projects:
            supabase.table("people_projects").insert({
                "person_id": person_id,
                "name": proj.get("name"),
                "url": proj.get("url"),
                "description": proj.get("description"),
            }).execute()

        return {"message": "Profile updated successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/uploadImage")
async def upload_image(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    try:
        auth_token = UploadImageKey()
        if not auth_token:
            raise HTTPException(status_code=500, detail="Failed to get upload auth token")

        contents = await file.read()

        response = requests.post(
            "https://imgbb.com/json",
            files={"source": (file.filename, contents, file.content_type)},
            data={
                "type": "file",
                "action": "upload",
                "auth_token": auth_token,
            },
            timeout=60,
        )

        result = response.json()

        if result.get("status_code") != 200:
            raise HTTPException(status_code=500, detail="Image upload failed")

        return {"url": result["image"]["url"]}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/uploadImage")
async def upload_image(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    try:
        auth_token = UploadImageKey()
        if not auth_token:
            raise HTTPException(status_code=500, detail="Failed to get upload auth token")

        contents = await file.read()

        timestamp = str(int(time.time() * 1000))

        response = requests.post(
            "https://imgbb.com/json",
            data={
                "type": "file",
                "action": "upload",
                "auth_token": auth_token,
                "timestamp": timestamp,
            },
            files={"source": (file.filename, contents, file.content_type)},
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            },
            timeout=60,
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
        raise HTTPException(status_code=500, detail=str(e))
