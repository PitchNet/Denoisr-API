from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
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
security = HTTPBearer()

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
# Helper Methods
# --------------------------
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject = payload.get("sub")  # Could be emailaddress or id

        if not subject:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: subject missing"
            )

        # Try to fetch by emailaddress first
        user = supabase.table("people").select("*").eq("id", subject).single().execute()
        if not user.data:
            # Fallback: try by id
            user = supabase.table("people").select("*").eq("id", subject).single().execute()

        if not user.data:
            raise HTTPException(status_code=401, detail="User not found")

        return user.data

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


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


@router.post("/fetchPeople", response_model=List[Dict[str, Any]])
def fetch_people(filters: Dict[str, Any], user: str = Depends(get_current_user)):
    try:
        # Base query with related data
        query = (
            supabase.table("people").select(
                "*, "
                "people_highlights(highlight), "
                "people_tags(tag), "
                "people_sections(id, title, people_section_items(item))"
            )
        )

        # Simple filtering similar to fetchJobs (optional)
        role = filters.get("role")
        experience = filters.get("experience")
        country = filters.get("country")
        city = filters.get("city")
        salary = filters.get("salary")

        if role:
            query = query.or_(
                f"headline.ilike.%{role}%,subheadline.ilike.%{role}%,intro.ilike.%{role}%"
            )

        if experience is not None:
            query = query.lte("experience", experience)

        if country:
            countries = [c.strip() for c in country.split(",") if c.strip()]
            if countries:
                or_conditions = ",".join([f"location.ilike.%{c}%" for c in countries])
                query = query.or_(or_conditions)

        if city:
            cities = [c.strip() for c in city.split(",") if c.strip()]
            if cities:
                or_conditions = ",".join([f"location.ilike.%{c}%" for c in cities])
                query = query.or_(or_conditions)

        if salary is not None:
            query = query.lte("salary", salary)

        people_res = query.execute()
        people = people_res.data or []

        result: List[Dict[str, Any]] = []

        for p in people:
            pid = p.get("id")

            highlights = [h["highlight"] for h in p.get("people_highlights", []) if "highlight" in h]
            tags = [t["tag"] for t in p.get("people_tags", []) if "tag" in t]

            sections_raw = p.get("people_sections", [])
            sections: List[Dict[str, Any]] = []
            for sec in sections_raw:
                sec_id = sec.get("id")
                title = sec.get("title")
                items = [it["item"] for it in sec.get("people_section_items", []) if "item" in it]
                sections.append({"title": title, "items": items})

            result.append({
                "id": pid,
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
            })

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fetchJobs", response_model=List[Dict[str, Any]])
def fetch_jobs(filters: Dict[str, Any], user: str = Depends(get_current_user)):

    try:
        # --------------------------
        # 1. Base query
        # --------------------------
        query = supabase.table("jobs").select("""
            *,
            job_highlights(highlight),
            job_tags(tag),
            job_sections(
                id,
                title,
                job_section_items(item)
            )
        """)

        role = filters.get("role")
        experience = filters.get("experience")
        country = filters.get("country")
        city = filters.get("city")
        salary = filters.get("salary")
        
        accepted_job_ids = []

        if user: 
            accepted_res = supabase.table("user_job_actions") \
                .select("job_id") \
                .eq("user_id", user["id"]) \
                .eq("action", "accepted") \
                .execute()

            accepted_job_ids = [a["job_id"] for a in (accepted_res.data or [])]
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
            countries = [c.strip() for c in country.split(",") if c.strip()]

            if countries:
                or_conditions = ",".join(
                    [f"location.ilike.%{c}%" for c in countries]
                )
                query = query.or_(or_conditions)

        if city:
            cities = [c.strip() for c in city.split(",") if c.strip()]

            if cities:
                or_conditions = ",".join(
                    [f"location.ilike.%{c}%" for c in cities]
                )
                query = query.or_(or_conditions)

        # Salary → max salary
        if salary is not None:
            query = query.lte("salary", salary)

        # Exclude accepted jobs
        if accepted_job_ids:
            query = query.not_.in_("id", accepted_job_ids)

        # --------------------------
        # 3. Fetch jobs
        # --------------------------
        jobs_res = query.execute()

        jobs = jobs_res.data or []

        if not jobs:
            return []

        # --------------------------
        # 5. Grouping
        # --------------------------
        result = []

        for job in jobs:
            result.append({
                "id": job["id"],
                "kind": "jobs",
                "headline": job.get("headline"),
                "subheadline": job.get("subheadline"),
                "organization": job.get("organization"),
                "location": job.get("location"),
                "experience": job.get("experience"),
                "salary": job.get("salary"),
                "intro": job.get("intro"),

                "highlights": [
                    h["highlight"] for h in job.get("job_highlights", [])
                ],

                "tags": [
                    t["tag"] for t in job.get("job_tags", [])
                ],

                "sections": [
                    {
                        "title": s["title"],
                        "items": [
                            i["item"] for i in s.get("job_section_items", [])
                        ]
                    }
                    for s in job.get("job_sections", [])
                ]
            })

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobAction")
def accept_job(payload: Dict[str, str], user: str = Depends(get_current_user)):

    job_id = payload.get("jobId")

    if not user or not job_id:
        raise HTTPException(status_code=400, detail="Missing fields")

    try:
        supabase.table("user_job_actions").upsert({
            "user_id": user["id"],
            "job_id": job_id,
            "action": "accepted"
        }).execute()

        return {"message": "Job accepted"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/peopleAction")
def connect_people(payload: Dict[str, str], user: str = Depends(get_current_user)):

    people_id = payload.get("peopleId")

    if not user or not people_id:
        raise HTTPException(status_code=400, detail="Missing fields")

    try:
        supabase.table("user_people_actions").upsert({
            "user_id": user["id"],
            "people_id": people_id,
            "action": "sent"
        }).execute()

        return {"message": "Connection request sent"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/InsertPeople", status_code=201)
def insert_people(people: List[Dict[str, Any]]):
    try:
        for person in people:
            person_payload = {
                "headline": person.get("headline"),
                "subheadline": person.get("subheadline"),
                "organization": person.get("organization"),
                "location": person.get("location"),
                "experience": person.get("experience"),
                "salary": person.get("salary"),
                "intro": person.get("intro"),
            }

            person_insert = (
                supabase.table("people").insert(person_payload).execute()
            )

            if not person_insert.data:
                raise HTTPException(status_code=500, detail="Person insert failed")

            person_id = person_insert.data[0]["id"]

            # Highlights
            highlights = person.get("highlights") or []
            if highlights:
                supabase.table("people_highlights").insert([
                    {"person_id": person_id, "highlight": h}
                    for h in highlights
                ]).execute()

            # Tags
            tags = person.get("tags") or []
            if tags:
                supabase.table("people_tags").insert([
                    {"person_id": person_id, "tag": t}
                    for t in tags
                ]).execute()

            # Sections + Items
            sections = person.get("sections") or []
            for section in sections:
                section_insert = (
                    supabase.table("people_sections")
                    .insert({"person_id": person_id, "title": section.get("title")})
                    .execute()
                )
                if not section_insert.data:
                    raise HTTPException(status_code=500, detail="Section insert failed")
                section_id = section_insert.data[0]["id"]
                items = section.get("items") or []
                if items:
                    supabase.table("people_section_items").insert([
                        {"section_id": section_id, "item": item}
                        for item in items
                    ]).execute()

        return {"message": "People inserted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
