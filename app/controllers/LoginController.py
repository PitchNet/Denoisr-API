from fastapi import APIRouter, HTTPException, status, Depends, Request, Response
from pydantic import BaseModel, EmailStr
from jose import jwt
from datetime import datetime, timedelta
import bcrypt
import os
import json
import re
from dotenv import load_dotenv
from supabase import create_client, Client
from typing import Dict, Any
from app.services.service import UploadImageKey
from app.services.email_service import send_password_reset_email, RESEND_API_KEY
from app.auth_utils import get_current_user_row, set_auth_cookie, clear_auth_cookie, create_reset_token, decode_reset_token
from apify_client import ApifyClient
from google import genai

# --------------------------
# Load ENV
# --------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --------------------------
# Router
# --------------------------
router = APIRouter(prefix="/LoginController", tags=["Login"])

# --------------------------
# Config
# --------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10080
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

# --------------------------
# Models (UPDATED for your payload)
# --------------------------
class SectionModel(BaseModel):
    title: str
    items: list[str] = []

class WorkExperienceModel(BaseModel):
    company: str | None = None
    role: str | None = None
    duration: str | None = None
    description: str | None = None

class ProjectModel(BaseModel):
    name: str | None = None
    link: str | None = None
    description: str | None = None

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    phoneNumber: str | None = None
    kind: str | None = "people"
    name: str | None = None
    currentRole: str | None = None
    organization: str | None = None
    location: str | None = None
    experience: int | None = None
    salary: int | None = None
    intro: str | None = None
    photo: str | None = None
    highlights: list[str] = []
    tags: list[str] = []
    sections: list[SectionModel] = []
    workExperience: list[WorkExperienceModel] = []
    projects: list[ProjectModel] = []


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    newPassword: str


# --------------------------
# Utils
# --------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def create_access_token(data: dict) -> str:
    payload = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def run_sql_script(script_name: str, context: dict):
    """
    Reads SQL file from app/scripts and executes via Supabase RPC
    """
    path = f"app/scripts/{script_name}.txt"

    with open(path, "r") as f:
        sql = f.read()

    # OPTIONAL: replace placeholders like {{email}}
    for k, v in context.items():
        sql = sql.replace(f"{{{{{k}}}}}", str(v))

    # Requires Postgres function:
    # create function exec_sql(query text) returns void ...
    response = supabase.rpc("exec_sql", {"query": sql}).execute()

    return response


# --------------------------
# Get current user
# --------------------------
def get_current_user(request: Request):
    return get_current_user_row(request, supabase)


# --------------------------
# ROUTES
# --------------------------

@router.post("/signup", status_code=201)
def signup(user: UserCreate, response: Response):

    # 1. Check if user exists in new People schema
    existing = supabase.table("people") \
        .select("emailaddress") \
        .eq("emailaddress", user.email) \
        .execute()

    if existing.data:
        raise HTTPException(status_code=400, detail="User already exists")

    # 2. Hash password
    hashed_pw = hash_password(user.password)

    # 3. Insert user (into new People schema)
    user_payload = {
        "emailaddress": user.email,
        "passwordhash": hashed_pw,
        "headline": user.name,
        "phonenumber": user.phoneNumber,
        "location": user.location,
        "subheadline": user.currentRole,
        "experience": user.experience,
        "salary": user.salary,
        "intro": user.intro,
        "organization": user.organization,
        #"workpreference": user.workPreference,
        #"country": None,
        "currentrole": user.currentRole,
        "introduction": user.intro,
        "name": user.name,
        "experience": user.experience,
        "photo": user.photo
    }

    insert = supabase.table("people").insert(user_payload).execute()

    if not insert.data:
        err = (insert.error or {}).get("message", "unknown")
        raise HTTPException(status_code=500, detail=f"signup: user creation failed — {err}")

    user_row = insert.data[0]
    user_id = user_row["id"]

    # 4. Highlights from payload
    person_id = user_id
    try:
        highlights = user.highlights or []
        if highlights:
            supabase.table("people_highlights").insert([
                {"person_id": person_id, "highlight": h}
                for h in highlights
            ]).execute()
    except Exception as e:
        print(f"[signup] Highlights insert failed (non-fatal): {type(e).__name__}: {e}")

    # 5. Tags
    tags = user.tags or []
    if tags:
        supabase.table("people_tags").insert([
            {"person_id": person_id, "tag": t}
            for t in tags
        ]).execute()

    # 6. Sections + Items
    sections = user.sections or []
    for section in sections:
        section_insert = (
            supabase.table("people_sections").insert({"person_id": person_id, "title": section.title}).execute()
        )
        if not section_insert.data:
            err = (section_insert.error or {}).get("message", "unknown")
            raise HTTPException(status_code=500, detail=f"signup: section insert failed — {err}")
        section_id = section_insert.data[0]["id"]
        items = section.items or []
        if items:
            supabase.table("people_section_items").insert([
                {"section_id": section_id, "item": item}
                for item in items
            ]).execute()

    # 7. Work experience
    work_experience = user.workExperience or []
    for we in work_experience:
        supabase.table("people_work_experience").insert({
            "person_id": person_id,
            "company": we.company,
            "role": we.role,
            "duration": we.duration,
            "description": we.description,
        }).execute()

    # 8. Projects
    projects = user.projects or []
    for proj in projects:
        supabase.table("people_projects").insert({
            "person_id": person_id,
            "name": proj.name,
            "url": proj.link,
            "description": proj.description,
        }).execute()

    token_sub = person_id if person_id else user_id
    token = create_access_token({"sub": token_sub})
    set_auth_cookie(response, token)

    created_user = dict(insert.data[0])
    created_user.pop("passwordhash", None)

    return {
        "message": "User created successfully",
        "user": created_user,
        "access_token": token,
    }


@router.post("/login")
def login(data: LoginRequest, response: Response):

    user = supabase.table("people") \
        .select("*") \
        .eq("emailaddress", data.email) \
        .single() \
        .execute()

    if not user.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(data.password, user.data["passwordhash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user.data["id"]})
    set_auth_cookie(response, token)

    safe_user = dict(user.data)
    safe_user.pop("passwordhash", None)

    return {"user": safe_user, "access_token": token}


@router.post("/logout")
def logout(response: Response):
    clear_auth_cookie(response)
    return {"message": "Logged out"}


@router.post("/forgotPassword")
def forgot_password(data: ForgotPasswordRequest):
    user = supabase.table("people").select("id, passwordhash").eq("emailaddress", data.email).execute()

    if not user.data:
        # Same response as the "found, email sent" case below — otherwise this
        # endpoint becomes an account-enumeration oracle.
        return {"message": "If that email is registered, you can reset its password."}

    person = user.data[0]
    token = create_reset_token(person["id"], person["passwordhash"])

    if RESEND_API_KEY:
        reset_link = f"{FRONTEND_BASE_URL.rstrip('/')}/reset-password?token={token}"
        if send_password_reset_email(data.email, reset_link):
            return {"message": "If that email is registered, a reset link is on its way."}
        print(f"[forgot_password] Resend delivery failed for {data.email}, falling back to inline token")

    # No email provider configured, or Resend delivery failed: hand the
    # token straight back so the UI can jump directly to the "set a new
    # password" screen instead of waiting on an email that will never
    # arrive. This is a deliberate product trade-off — it means anyone
    # who knows or guesses a registered email can reset that account's
    # password with no proof of inbox access. Set RESEND_API_KEY (and
    # a verified domain) to restore real email verification.
    return {"message": "No email service is available — continue below to set a new password.", "token": token}


@router.post("/resetPassword")
def reset_password(data: ResetPasswordRequest):
    if len(data.newPassword) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    user = decode_reset_token(data.token, supabase)
    new_hash = hash_password(data.newPassword)
    supabase.table("people").update({"passwordhash": new_hash}).eq("id", user["id"]).execute()

    return {"message": "Password updated. You can now log in."}


@router.get("/profile")
def profile(current_user: dict = Depends(get_current_user)):
    return {
        "message": f"Welcome {current_user['emailaddress']}",
        "user": current_user
    }


@router.get("/keepAlive")
def keepAlive():
    return ("Hi!")


@router.post("/linkedinImport")
def linkedin_import(payload: Dict[str, Any]):
    try:
        url = payload.get("url")
        if not url:
            raise HTTPException(status_code=400, detail="LinkedIn URL is required")

        if not APIFY_TOKEN:
            raise HTTPException(status_code=500, detail="APIFY_TOKEN not configured")
        if not GOOGLE_API_KEY:
            raise HTTPException(status_code=500, detail="GOOGLE_API_KEY not configured")

        # Step 1: Scrape LinkedIn via Apify
        apify = ApifyClient(APIFY_TOKEN)

        run_input = {
            "profileScraperMode": "Profile details no email ($4 per 1k)",
            "queries": [url],
        }

        run = apify.actor("LpVuK3Zozwuipa5bp").call(run_input=run_input)

        linkedin_data = []
        profile_picture = None
        for item in apify.dataset(run.default_dataset_id).iterate_items():
            linkedin_data.append(item)
            if not profile_picture:
                profile_picture = item.get("profilePicture") or item.get("profilePic") or item.get("photo")

        # Step 2: Ask Gemma to restructure into signup format
        prompt = f"""You are given LinkedIn profile data. Restructure it into the exact JSON format shown below. Do not include any text outside the JSON. Return ONLY valid JSON.

Example output:
{{
  "headline": "Aanya Mehta",
  "subheadline": "Frontend Engineer",
  "organization": "Proof-led builder with marketplace and fintech experience",
  "location": "Bengaluru, India",
  "experience": 5,
  "salary": 80,
  "intro": "Built complex React platforms used by operations teams to make faster decisions with less dashboard noise.",
  "highlights": ["React", "TypeScript", "Design systems"],
  "tags": ["Open to roles", "Remote", "Available in 30 days"],
  "sections": [
    {{"title": "Proof of work", "items": ["Redesigned internal review workflows and cut task time by 38%.", "Built a reusable component system used across three product teams."]}},
    {{"title": "Intent and fit", "items": ["Prefers product teams with clear ownership and measurable outcomes.", "Strong fit for structured hiring, workflow SaaS, and trust-heavy products."]}}
  ],
  "workExperience": [
    {{"company": "Example Corp", "role": "Frontend Engineer", "duration": "Jan 2020 - Present", "description": "Built and maintained scalable UI systems."}}
  ],
  "projects": [],
  "photo": ""
}}

Now restructure this LinkedIn data:
{linkedin_data}"""

        gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        response = gemini_client.models.generate_content(
            model="gemma-4-31b-it",
            contents=prompt,
        )

        text = response.text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)

        if profile_picture and not result.get("photo"):
            result["photo"] = profile_picture

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"linkedin_import: {type(e).__name__}: {e}")
