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

    # 1. Check if user exists
    existing = supabase.table("users") \
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
        "name": user.name,
        "phonenumber": user.phoneNumber,
        "country": user.country,
        "currentrole": user.currentRole,
        "yearsofexperience": user.yearsOfExperience,
        "availablefrom": user.availableFrom,
        "portfoliourl": user.portfolioUrl,
        "workpreference": user.workPreference,
        "introduction": user.proofOfWork,
    }

    insert = supabase.table("users").insert(user_payload).execute()

    if not insert.data:
        raise HTTPException(status_code=500, detail="User creation failed")

    user_row = insert.data[0]
    user_id = user_row["id"]

    # 4. Fetch all skill IDs in one query (OPTIMIZED)
    skill_names = [s.name for s in user.skills]

    skills_res = supabase.table("skills") \
        .select("id, name") \
        .in_("name", skill_names) \
        .execute()

    if not skills_res.data:
        raise HTTPException(status_code=400, detail="No matching skills found")

    skills_map = {s["name"]: s["id"] for s in skills_res.data}

    # 5. Insert into UserSkillMapping
    mappings = []

    for skill in user.skills:
        skill_id = skills_map.get(skill.name)

        if not skill_id:
            raise HTTPException(
                status_code=400,
                detail=f"Skill not found: {skill.name}"
            )

        mappings.append({
            "userid": user_id,
            "skillid": skill_id
        })

    if mappings:
        supabase.table("userskillmapping").insert(mappings).execute()

    return {
        "message": "User created successfully",
        "user": insert.data[0]
    }


@router.post("/login")
def login(data: LoginRequest):

    user = supabase.table("users") \
        .select("*") \
        .eq("emailaddress", data.email) \
        .single() \
        .execute()

    if not user.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(data.password, user.data["passwordhash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user.data["emailaddress"]})

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