from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
from datetime import datetime, timedelta
import bcrypt
import os
from dotenv import load_dotenv
from supabase import create_client, Client

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
router = APIRouter(prefix="/LoginController", tags=["Login"])

# --------------------------
# Config
# --------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# --------------------------
# OAuth2
# --------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/LoginController/login")

# --------------------------
# Models (UPDATED for your payload)
# --------------------------
class Skill(BaseModel):
    name: str
    proficiency: int

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None
    phoneNumber: str | None = None
    country: str | None = None
    currentRole: str | None = None
    yearsOfExperience: int | None = None
    availableFrom: str | None = None
    skills: list[Skill] = []
    portfolioUrl: str | None = None
    workPreference: str | None = None
    proofOfWork: str | None = None
    organization: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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
def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")

        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = supabase.table("users").select("*").eq("email", email).single().execute()

        if not user.data:
            raise HTTPException(status_code=401, detail="User not found")

        return user.data

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# --------------------------
# ROUTES
# --------------------------

@router.post("/signup", status_code=201)
def signup(user: UserCreate):

    # 1. Check if user exists in new People schema
    existing = supabase.table("people") \
        .select("emailaddress") \
        .eq("emailaddress", user.email) \
        .execute()

    if existing.data:
        raise HTTPException(status_code=400, detail="User already exists")

    # 2. Hash password
    hashed_pw = hash_password(user.password)

    # 3. Insert user
    user_payload = {
        "emailaddress": user.email,
        "passwordhash": hashed_pw,
        "headline": user.name,
        "phonenumber": user.phoneNumber,
        "location": user.country,
        "subheadline": user.currentRole,
        "experience": user.yearsOfExperience,
        "availablefrom": user.availableFrom,
        "portfoliourl": user.portfolioUrl,
        "workpreference": user.workPreference,
        "intro": user.proofOfWork,
        "organization": user.organization
    }

    insert = supabase.table("people").insert(user_payload).execute()

    if not insert.data:
        raise HTTPException(status_code=500, detail="User creation failed")

    user_row = insert.data[0]
    user_id = user_row["id"]

    # 4. Map highlights (treat user.skills as highlights in new schema)
    person_id = user_id
    try:
        highlights = user.skills or []
        if highlights:
            supabase.table("people_highlights").insert([
                {"person_id": person_id, "highlight": s.name}
                for s in highlights
            ]).execute()
    except Exception:
        pass

    token_sub = person_id if person_id else user_id
    token = create_access_token({"sub": token_sub})

    return {
        "message": "User created successfully",
        "user": insert.data[0],
        "access_token": token
    }


@router.post("/login")
def login(data: LoginRequest):

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

    return {
        "access_token": token,
        "token_type": "bearer"
    }


@router.get("/profile")
def profile(current_user: dict = Depends(get_current_user)):
    return {
        "message": f"Welcome {current_user['email']}",
        "user": current_user
    }


@router.get("/keepAlive")
def keepAlive():
    return ("Hi!")