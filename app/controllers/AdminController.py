from fastapi import APIRouter, HTTPException, Depends, Request
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import Dict, Any
from app.auth_utils import get_current_user_row, is_admin
from app.controllers.NotificationController import send_push

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/AdminController", tags=["Admin"])


def get_current_user(request: Request):
    return get_current_user_row(request, supabase)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/isAdmin")
def check_is_admin(user: dict = Depends(get_current_user)):
    return {"isAdmin": is_admin(user)}


@router.get("/pendingCompanies")
def pending_companies(status: str = "unverified", user: dict = Depends(require_admin)):
    try:
        companies = supabase.table("companies").select("*").eq("verification_status", status).execute()
        return {"companies": companies.data or []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"pending_companies: {type(e).__name__}: {e}")


@router.post("/reviewCompany")
def review_company(payload: Dict[str, Any], user: dict = Depends(require_admin)):
    try:
        company_id = payload.get("companyId")
        decision = payload.get("decision")
        notes = payload.get("notes")

        if not company_id:
            raise HTTPException(status_code=400, detail="companyId is required")
        if decision not in ("verified", "rejected"):
            raise HTTPException(status_code=400, detail="decision must be 'verified' or 'rejected'")

        update = {
            "verification_status": decision,
            "verification_notes": notes,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "verified_by": user["id"],
        }
        result = supabase.table("companies").update(update).eq("id", company_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Company not found")

        owner = supabase.table("people").select("id").eq("companyid", company_id).execute()
        for row in owner.data or []:
            if decision == "verified":
                send_push(row["id"], "Company verified", "Your company profile has been verified.", {"type": "company_verification"})
            else:
                reason = f" Reason: {notes}" if notes else ""
                send_push(row["id"], "Company verification needs changes", f"Your company profile was not approved.{reason}", {"type": "company_verification"})

        return {"message": "Company reviewed", "companyId": company_id, "status": decision}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"review_company: {type(e).__name__}: {e}")
