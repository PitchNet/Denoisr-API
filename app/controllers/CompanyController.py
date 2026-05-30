from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import List, Dict, Any
from datetime import datetime

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
                raise HTTPException(status_code=500, detail="Company creation failed")
            company_id = insert.data[0]["id"]

        supabase.table("people").update({"companyid": company_id}).eq("id", user["id"]).execute()
        return {"message": "Company saved", "companyId": company_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobDetails")
def job_details(payload: Dict[str, Any], user: dict = Depends(get_current_user)):
    try:
        company_id = user.get("companyid")
        if not company_id:
            raise HTTPException(status_code=400, detail="No company associated with this user")

        job_id = payload.get("id")

        job_payload = {
            "headline": payload.get("headline"),
            "subheadline": payload.get("subheadline"),
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
                raise HTTPException(status_code=500, detail="Job creation failed")
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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))
