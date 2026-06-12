from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import List, Dict, Any
from datetime import datetime, timezone
from app.controllers.NotificationController import send_push

load_dotenv()
security = HTTPBearer()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/CompanyController", tags=["Company"])

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
            raise HTTPException(status_code=401, detail="User not found")

        return user.data

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


@router.post("/companyDetails")
def company_details(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    try:
        company_id = payload.get("companyId") or user.get("companyId")

        company_data = {
            "name": payload.get("name"),
            "photo": payload.get("photo"),
            "website": payload.get("website"),
            "size": payload.get("size"),
            "address": payload.get("address"),
            "description": payload.get("description"),
            "phone": payload.get("phone"),
            "year_founded": payload.get("yearFounded"),
            "tags": payload.get("tags"),
            "commitments": payload.get("commitments"),
        }
        company_data = {k: v for k, v in company_data.items() if v is not None}

        if company_id:
            supabase.table("companies").update(company_data).eq("id", company_id).execute()
        else:
            insert = supabase.table("companies").insert(company_data).execute()
            if not insert.data:
                err = (insert.error or {}).get("message", "unknown")
                raise HTTPException(status_code=500, detail=f"company_details: create failed — {err}")
            company_id = insert.data[0]["id"]

        supabase.table("people").update({"companyid": company_id}).eq("id", user["id"]).execute()
        return {"message": "Company saved", "companyId": company_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"company_details: {type(e).__name__}: {e}")


@router.get("/getCompany")
def get_company(user: dict = Depends(get_current_user)):
    try:
        company_id = user.get("companyid")
        if not company_id:
            return {"company": None}

        company = supabase.table("companies").select("*").eq("id", company_id).single().execute()

        if not company.data:
            return {"company": None}

        c = company.data

        return {
            "company": {
                "name": c.get("name"),
                "photo": c.get("photo"),
                "website": c.get("website"),
                "size": c.get("size"),
                "address": c.get("address"),
                "description": c.get("description"),
                "phone": c.get("phone"),
                "yearFounded": c.get("year_founded"),
                "tags": c.get("tags") or [],
                "commitments": c.get("commitments"),
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get_company: {type(e).__name__}: {e}")


@router.post("/jobDetails")
def job_details(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    try:
        company_id = user.get("companyid")
        if not company_id:
            raise HTTPException(status_code=400, detail="No company associated with this user")

        # Fetch company name for subheadline
        company_res = supabase.table("companies").select("name").eq("id", company_id).single().execute()
        company_name = company_res.data.get("name") if company_res.data else None

        job_id = payload.get("id")

        job_payload = {
            "headline": payload.get("headline"),
            "subheadline": company_name,
            "organization": payload.get("organization"),
            "location": payload.get("location"),
            "experience": payload.get("experience"),
            "salary": payload.get("salary"),
            "intro": payload.get("intro"),
            "company_id": company_id,
        }
        job_payload = {k: v for k, v in job_payload.items() if v is not None}

        if job_id:
            supabase.table("jobs").update(job_payload).eq("id", job_id).execute()
        else:
            insert = supabase.table("jobs").insert(job_payload).execute()
            if not insert.data:
                err = (insert.error or {}).get("message", "unknown")
                raise HTTPException(status_code=500, detail=f"job_details: create failed — {err}")
            job_id = insert.data[0]["id"]

        # Replace highlights
        supabase.table("job_highlights").delete().eq("job_id", job_id).execute()
        highlights = payload.get("highlights") or []
        if highlights:
            supabase.table("job_highlights").insert([
                {"job_id": job_id, "highlight": h} for h in highlights
            ]).execute()

        # Replace tags
        supabase.table("job_tags").delete().eq("job_id", job_id).execute()
        tags = payload.get("tags") or []
        if tags:
            supabase.table("job_tags").insert([
                {"job_id": job_id, "tag": t} for t in tags
            ]).execute()

        # Replace sections + items
        existing = supabase.table("job_sections").select("id").eq("job_id", job_id).execute()
        for sec in (existing.data or []):
            supabase.table("job_section_items").delete().eq("section_id", sec["id"]).execute()
        supabase.table("job_sections").delete().eq("job_id", job_id).execute()

        sections = payload.get("sections") or []
        for section in sections:
            sec_insert = supabase.table("job_sections").insert({
                "job_id": job_id, "title": section.get("title")
            }).execute()
            if sec_insert.data:
                sec_id = sec_insert.data[0]["id"]
                items = section.get("items") or []
                if items:
                    supabase.table("job_section_items").insert([
                        {"section_id": sec_id, "item": item} for item in items
                    ]).execute()

        return {"message": "Job saved", "jobId": job_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"job_details: {type(e).__name__}: {e}")


@router.get("/companyJobs")
def company_jobs(user: dict = Depends(get_current_user)):
    try:
        company_id = user.get("companyid")
        if not company_id:
            return []

        jobs_res = supabase.table("jobs").select("""
            *,
            job_highlights(highlight),
            job_tags(tag),
            job_sections(id, title, job_section_items(item))
        """).eq("company_id", company_id).execute()

        jobs = jobs_res.data or []

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
        raise HTTPException(status_code=500, detail=f"company_jobs: {type(e).__name__}: {e}")


def _relative_time(dt_str: str) -> str:
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        days = diff.days
        if days < 1:
            hours = int(diff.total_seconds() // 3600)
            if hours < 1:
                minutes = int(diff.total_seconds() // 60)
                return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if days == 1:
            return "1 day ago"
        if days < 7:
            return f"{days} days ago"
        if days < 30:
            weeks = days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        if days < 365:
            months = days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        years = days // 365
        return f"{years} year{'s' if years != 1 else ''} ago"
    except Exception:
        return dt_str or ""


@router.post("/jobApplicants")
def job_applicants(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    try:
        job_id = payload.get("jobId")
        if not job_id:
            raise HTTPException(status_code=400, detail="jobId required")

        actions = supabase.table("user_job_actions") \
            .select("user_id, created_at, status") \
            .eq("job_id", job_id) \
            .eq("action", "accepted") \
            .execute()

        if not actions.data:
            return []

        user_ids = [a["user_id"] for a in actions.data]
        created_map = {a["user_id"]: a.get("created_at", "") for a in actions.data}
        status_map = {a["user_id"]: a.get("status", "new") for a in actions.data}

        people = supabase.table("people").select(
            "*, "
            "people_highlights(highlight), "
            "people_tags(tag), "
            "people_sections(id, title, people_section_items(item)), "
            "people_work_experience(company, role, duration, description), "
            "people_projects(name, url, description)"
        ).in_("id", user_ids).execute()

        people_map = {p["id"]: p for p in (people.data or [])}

        result = []
        for uid in user_ids:
            p = people_map.get(uid)
            if not p:
                continue

            highlights = [h["highlight"] for h in p.get("people_highlights", []) if "highlight" in h]
            tags = [t["tag"] for t in p.get("people_tags", []) if "tag" in t]

            sections_raw = p.get("people_sections", [])
            sections = []
            for sec in sections_raw:
                items = [it["item"] for it in sec.get("people_section_items", []) if "item" in it]
                sections.append({"title": sec["title"], "items": items})

            work_experience = [
                {
                    "company": we.get("company"),
                    "role": we.get("role"),
                    "duration": we.get("duration"),
                    "description": we.get("description"),
                }
                for we in (p.get("people_work_experience") or [])
            ]

            projects = [
                {
                    "name": proj.get("name"),
                    "url": proj.get("url"),
                    "description": proj.get("description"),
                }
                for proj in (p.get("people_projects") or [])
            ]

            result.append({
                "id": p["id"],
                "name": p.get("headline") or p.get("name"),
                "role": p.get("subheadline"),
                "org": p.get("organization"),
                "location": p.get("location"),
                "experience": p.get("experience"),
                "salary": p.get("salary"),
                "intro": p.get("intro"),
                "photo": p.get("photo") or "",
                "highlights": highlights,
                "tags": tags,
                "sections": sections,
                "workExperience": work_experience,
                "projects": projects,
                "appliedDate": _relative_time(created_map.get(uid, "")),
                "status": status_map.get(uid, "new")
            })

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"job_applicants: {type(e).__name__}: {e}")


@router.get("/jobApplicantCounts")
def job_applicant_counts(user: dict = Depends(get_current_user)):
    try:
        company_id = user.get("companyid")
        if not company_id:
            return []

        jobs = supabase.table("jobs").select("id").eq("company_id", company_id).execute()
        job_ids = [j["id"] for j in (jobs.data or [])]
        if not job_ids:
            return []

        actions = supabase.table("user_job_actions") \
            .select("job_id") \
            .in_("job_id", job_ids) \
            .eq("action", "accepted") \
            .execute()

        counts: Dict[str, int] = {}
        for a in (actions.data or []):
            jid = a["job_id"]
            counts[jid] = counts.get(jid, 0) + 1

        return [{"jobId": jid, "count": counts.get(jid, 0)} for jid in job_ids]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"job_applicant_counts: {type(e).__name__}: {e}")


@router.post("/jobApplicantStatus")
def job_applicant_status(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    try:
        job_id = payload.get("jobId")
        person_id = payload.get("personId")
        status = payload.get("status")

        if not job_id or not person_id or not status:
            raise HTTPException(status_code=400, detail="jobId, personId, and status required")

        update: Dict[str, Any] = {"status": status}

        supabase.table("user_job_actions") \
            .update(update) \
            .eq("job_id", job_id) \
            .eq("user_id", person_id) \
            .eq("action", "accepted") \
            .execute()

        status_labels = {
            "new": "New", "submitted": "Submitted", "reviewing": "Reviewing",
            "shortlisted": "Shortlisted", "messaged": "Messaged",
            "hired": "Hired", "passed": "Rejected",
        }
        job_res = supabase.table("jobs").select("headline").eq("id", job_id).single().execute()
        job_title = job_res.data.get("headline", "a position") if job_res.data else "a position"
        label = status_labels.get(status, status)
        send_push(
            person_id,
            "Application update",
            f"Your application for {job_title} is now {label}.",
            {"type": "job_status", "jobId": job_id},
        )

        return {"message": "Status updated"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"job_applicant_status: {type(e).__name__}: {e}")
