from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os
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
            "people_sections(id, title, people_section_items(item))"
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
            "highlights": highlights,
            "tags": tags,
            "sections": sections,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
