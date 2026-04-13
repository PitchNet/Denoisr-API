from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
from datetime import datetime, timedelta
import bcrypt
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import List, Dict, Any
from collections import defaultdict
# --------------------------
# Load ENV
# --------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --------------------------
# Router
# --------------------------
router = APIRouter(prefix="/FeedController", tags=["Feed"])

# --------------------------
# Config
# --------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# --------------------------
# ROUTES
# --------------------------
@router.post("/InsertJobs", status_code=201)
def insert_jobs(jobs: List[Dict[str, Any]]):

    try:
        for job in jobs:

            # --------------------------
            # 1. Insert Job
            # --------------------------
            job_payload = {
                "headline": job.get("headline"),
                "subheadline": job.get("subheadline"),
                "organization": job.get("organization"),
                "location": job.get("location"),
                "experience": job.get("experience"),
                "salary": job.get("salary"),
                "intro": job.get("intro"),
            }

            job_insert = (
                supabase.table("jobs")
                .insert(job_payload)
                .execute()
            )

            if not job_insert.data:
                raise HTTPException(status_code=500, detail="Job insert failed")

            job_id = job_insert.data[0]["id"]  # ✅ correct UUID source

            # --------------------------
            # 2. Highlights
            # --------------------------
            highlights = job.get("highlights") or []
            if highlights:
                supabase.table("job_highlights").insert([
                    {"job_id": job_id, "highlight": h}
                    for h in highlights
                ]).execute()

            # --------------------------
            # 3. Tags
            # --------------------------
            tags = job.get("tags") or []
            if tags:
                supabase.table("job_tags").insert([
                    {"job_id": job_id, "tag": t}
                    for t in tags
                ]).execute()

            # --------------------------
            # 4. Sections + Items
            # --------------------------
            sections = job.get("sections") or []

            for section in sections:

                section_insert = (
                    supabase.table("job_sections")
                    .insert({
                        "job_id": job_id,
                        "title": section.get("title")
                    })
                    .execute()
                )

                if not section_insert.data:
                    raise HTTPException(status_code=500, detail="Section insert failed")

                section_id = section_insert.data[0]["id"]

                items = section.get("items") or []
                if items:
                    supabase.table("job_section_items").insert([
                        {"section_id": section_id, "item": item}
                        for item in items
                    ]).execute()

        return {"message": "Jobs inserted successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/fetchJobs", response_model=List[Dict[str, Any]])
def fetch_jobs(filters: Dict[str, Any]):

    try:
        # --------------------------
        # 1. Base query
        # --------------------------
        query = supabase.table("jobs").select("*")

        role = filters.get("role")
        experience = filters.get("experience")
        country = filters.get("country")
        city = filters.get("city")
        salary = filters.get("salary")

        # --------------------------
        # 2. Filtering logic
        # --------------------------

        # Role → search in headline + subheadline + intro
        if role:
            query = query.or_(
                f"headline.ilike.%{role}%,"
                f"subheadline.ilike.%{role}%,"
                f"intro.ilike.%{role}%"
            )

        # Experience → max years
        if experience is not None:
            query = query.lte("experience", experience)

        # Country / City → requires DB columns OR fallback text search
        if country:
            query = query.ilike("location", f"%{country}%")

        if city:
            query = query.ilike("location", f"%{city}%")

        # Salary → max salary
        if salary is not None:
            query = query.lte("salary", salary)

        # --------------------------
        # 3. Fetch jobs
        # --------------------------
        jobs_res = query.execute()
        jobs = jobs_res.data or []

        if not jobs:
            return []

        job_ids = [j["id"] for j in jobs]

        # --------------------------
        # 4. Fetch relations (batched)
        # --------------------------
        highlights = supabase.table("job_highlights") \
            .select("*").in_("job_id", job_ids).execute().data or []

        tags = supabase.table("job_tags") \
            .select("*").in_("job_id", job_ids).execute().data or []

        sections = supabase.table("job_sections") \
            .select("*").in_("job_id", job_ids).execute().data or []

        section_ids = [s["id"] for s in sections]

        items = []
        if section_ids:
            items = supabase.table("job_section_items") \
                .select("*").in_("section_id", section_ids).execute().data or []

        # --------------------------
        # 5. Grouping
        # --------------------------
        highlights_map = defaultdict(list)
        for h in highlights:
            highlights_map[h["job_id"]].append(h["highlight"])

        tags_map = defaultdict(list)
        for t in tags:
            tags_map[t["job_id"]].append(t["tag"])

        sections_map = defaultdict(list)
        for s in sections:
            sections_map[s["job_id"]].append(s)

        items_map = defaultdict(list)
        for i in items:
            items_map[i["section_id"]].append(i["item"])

        # --------------------------
        # 6. Build response
        # --------------------------
        result = []

        for job in jobs:

            job_id = job["id"]

            result.append({
                "id": job_id,
                "headline": job.get("headline"),
                "subheadline": job.get("subheadline"),
                "organization": job.get("organization"),
                "location": job.get("location"),
                "experience": job.get("experience"),
                "salary": job.get("salary"),
                "intro": job.get("intro"),

                "highlights": highlights_map.get(job_id, []),
                "tags": tags_map.get(job_id, []),

                "sections": [
                    {
                        "title": s.get("title"),
                        "items": items_map.get(s["id"], [])
                    }
                    for s in sections_map.get(job_id, [])
                ]
            })

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))