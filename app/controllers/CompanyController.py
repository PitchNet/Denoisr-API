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

        supabase.table("people").update({"companyId": company_id}).eq("id", user["id"]).execute()
        return {"message": "Company saved", "companyId": company_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
