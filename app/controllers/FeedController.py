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
from app.controllers.NotificationController import send_push
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
FETCH_BATCH_SIZE = int(os.getenv("FETCH_BATCH_SIZE", "10"))
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
                err = (job_insert.error or {}).get("message", "unknown")
                raise HTTPException(status_code=500, detail=f"insert_jobs: insert failed — {err}")

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
                    err = (section_insert.error or {}).get("message", "unknown")
                    raise HTTPException(status_code=500, detail=f"insert_jobs: section insert failed — {err}")

                section_id = section_insert.data[0]["id"]

                # 4. Items
                items = section.get("items") or []
                if items:
                    supabase.table("job_section_items").insert([
                        {"section_id": section_id, "item": item}
                        for item in items
                    ]).execute()

        return {"message": "Jobs inserted successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert_jobs: {type(e).__name__}: {e}")


@router.post("/fetchPeople", response_model=Dict[str, Any])
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

        # Exclude current user
        query = query.neq("id", user["id"])

        # Only show profiles that are visible in the swipe feed
        query = query.eq("profile_visible", True)

        role = filters.get("role")
        experience = filters.get("experience")
        country = filters.get("country")
        city = filters.get("city")
        salary = filters.get("salary")

        bookmarked = filters.get("bookmarked")
        search = filters.get("search")
        cursor = filters.get("cursor")
        batch_size = filters.get("batch_size") or FETCH_BATCH_SIZE

        if bookmarked:
            bookmark_res = supabase.table("user_people_actions") \
                .select("people_id") \
                .eq("user_id", user["id"]) \
                .eq("action", "bookmark") \
                .execute()
            bookmark_ids = [b["people_id"] for b in (bookmark_res.data or [])]
            if not bookmark_ids:
                return []
            query = query.in_("id", bookmark_ids)
        else:
            interactions = supabase.table("user_people_actions") \
                .select("user_id, people_id, action") \
                .or_(
                    f"user_id.eq.{user['id']},"
                    f"people_id.eq.{user['id']}"
                ) \
                .in_("action", ["sent", "connected"]) \
                .execute()

            excluded_ids = set()
            for row in (interactions.data or []):
                if row.get("user_id") == user["id"]:
                    excluded_ids.add(row["people_id"])
                elif row.get("action") == "connected" and row.get("people_id") == user["id"]:
                    excluded_ids.add(row["user_id"])

            if excluded_ids:
                query = query.not_.in_("id", list(excluded_ids))

        # Search → broad match across main fields + related tables
        if search and search.strip():
            q = search.strip()
            search_ids = set()

            main_res = supabase.table("people").select("id").or_(
                f"headline.ilike.%{q}%,"
                f"subheadline.ilike.%{q}%,"
                f"organization.ilike.%{q}%,"
                f"location.ilike.%{q}%"
            ).execute()
            for r in (main_res.data or []):
                search_ids.add(r["id"])

            hl_res = supabase.table("people_highlights").select("people_id").ilike("highlight", f"%{q}%").execute()
            for r in (hl_res.data or []):
                search_ids.add(r["people_id"])

            tag_res = supabase.table("people_tags").select("people_id").ilike("tag", f"%{q}%").execute()
            for r in (tag_res.data or []):
                search_ids.add(r["people_id"])

            item_res = supabase.table("people_section_items").select("section_id").ilike("item", f"%{q}%").execute()
            sec_ids_with_match = [r["section_id"] for r in (item_res.data or [])]
            if sec_ids_with_match:
                sec_res = supabase.table("people_sections").select("person_id").in_("id", sec_ids_with_match).execute()
                for r in (sec_res.data or []):
                    search_ids.add(r["people_id"])

            if not search_ids:
                return []
            query = query.in_("id", list(search_ids))

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

        # Count total matching rows (before cursor/limit)
        count_known = False
        total_count = 0
        count_query = supabase.table("people").select("id").neq("id", user["id"]).eq("profile_visible", True)
        if bookmarked:
            if not bookmark_ids:
                total_count = 0
                count_known = True
            else:
                count_query = count_query.in_("id", bookmark_ids)
        else:
            if excluded_ids:
                count_query = count_query.not_.in_("id", list(excluded_ids))
        if search and search.strip() and search_ids:
            count_query = count_query.in_("id", list(search_ids))
        if role:
            count_query = count_query.or_(f"headline.ilike.%{role}%,subheadline.ilike.%{role}%,intro.ilike.%{role}%")
        if experience is not None:
            count_query = count_query.lte("experience", experience)
        if country:
            countries_ct = [c.strip() for c in country.split(",") if c.strip()]
            if countries_ct:
                or_ct = ",".join([f"location.ilike.%{c}%" for c in countries_ct])
                count_query = count_query.or_(or_ct)
        if city:
            cities_ct = [c.strip() for c in city.split(",") if c.strip()]
            if cities_ct:
                or_ct = ",".join([f"location.ilike.%{c}%" for c in cities_ct])
                count_query = count_query.or_(or_ct)
        if salary is not None:
            count_query = count_query.lte("salary", salary)
        if not count_known:
            count_result = count_query.execute()
            total_count = len(count_result.data or [])

        # Pagination
        if cursor:
            c = supabase.table("people").select("created_at, id").eq("id", cursor).single().execute()
            if c.data:
                cursor_time = c.data["created_at"]
                query = query.or_(
                    f"created_at.lt.{cursor_time},"
                    f"and(created_at.eq.{cursor_time},id.lt.{cursor})"
                )

        query = query.order("created_at", desc=True).order("id", desc=True).limit(batch_size + 1)

        people_res = query.execute()
        people = people_res.data or []

        has_more = len(people) > batch_size
        if has_more:
            people.pop()

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
                "photo": p.get("photo"),
                "highlights": highlights,
                "tags": tags,
                "sections": sections,
            })

        return {
            "items": result,
            "next_cursor": result[-1]["id"] if has_more else None,
            "has_more": has_more,
            "total_count": total_count,
        }


    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fetch_people: {type(e).__name__}: {e}")


@router.get("/getConnections", response_model=List[Dict[str, Any]])
def get_connections(q: str | None = None, user: dict = Depends(get_current_user)):
    try:
        # Fetch connected person IDs and their connection timestamps
        connected_res = supabase.table("user_people_actions") \
            .select("people_id, created_at") \
            .eq("user_id", user["id"]) \
            .eq("action", "connected") \
            .execute()

        connected_ids = set()
        connected_at_map: Dict[str, str] = {}
        for c in (connected_res.data or []):
            pid = c["people_id"]
            connected_ids.add(pid)
            connected_at_map[pid] = c.get("created_at")

        # Build map of person_id -> conversation_id
        conversation_map: Dict[str, str] = {}
        if connected_ids:
            my_parts = supabase.table("conversation_participants") \
                .select("conversation_id") \
                .eq("user_id", user["id"]) \
                .execute()

            my_conv_ids = [c["conversation_id"] for c in (my_parts.data or [])]

            if my_conv_ids:
                their_parts = supabase.table("conversation_participants") \
                    .select("conversation_id, user_id") \
                    .in_("user_id", list(connected_ids)) \
                    .in_("conversation_id", my_conv_ids) \
                    .execute()

                for p in (their_parts.data or []):
                    conversation_map[p["user_id"]] = p["conversation_id"]

        # Fetch last message per conversation
        last_message_map: Dict[str, Dict[str, Any]] = {}
        if conversation_map:
            conv_ids = list(set(conversation_map.values()))
            msgs_res = supabase.table("messages") \
                .select("id, conversation_id, sender_id, content, created_at") \
                .in_("conversation_id", conv_ids) \
                .order("created_at", desc=True) \
                .execute()

            seen = set()
            for m in (msgs_res.data or []):
                cid = m["conversation_id"]
                if cid not in seen:
                    seen.add(cid)
                    last_message_map[cid] = m

        query = supabase.table("people").select(
            "*, "
            "people_highlights(highlight), "
            "people_tags(tag), "
            "people_sections(id, title, people_section_items(item))"
        )

        # Only include connected people
        if connected_ids:
            query = query.in_("id", list(connected_ids))
        else:
            query = query.limit(0)

        people_res = query.execute()
        people = people_res.data or []

        def make_avatar(name: str | None) -> str:
            if not name:
                return "??"
            parts = name.strip().split()
            initials = "".join(p[0].upper() for p in parts if p)
            return initials[:2]

        def make_preview(intro: str | None) -> str:
            if not intro:
                return ""
            return intro.strip()

        result: List[Dict[str, Any]] = []

        for p in people:
            pid = p["id"]
            highlights = [h["highlight"] for h in p.get("people_highlights", []) if "highlight" in h]
            tags = [t["tag"] for t in p.get("people_tags", []) if "tag" in t]

            sections_raw = p.get("people_sections", [])
            details: List[Dict[str, Any]] = []
            for sec in sections_raw:
                title = sec.get("title")
                items = [it["item"] for it in sec.get("people_section_items", []) if "item" in it]
                body = ". ".join(items)
                if title and body:
                    details.append({"title": title, "body": body})

            result.append({
                "id": pid,
                "name": p.get("headline"),
                "preview": make_preview(p.get("intro")),
                "avatar": make_avatar(p.get("headline")),
                "role": p.get("subheadline"),
                "status": tags[0] if tags else "Open to roles",
                "openable": True,
                "chips": highlights,
                "details": details,
                "photo": p.get("photo"),
                "connected": pid in connected_ids,
                "conversationId": conversation_map.get(pid),
                "lastMessage": last_message_map.get(conversation_map.get(pid)),
            })

        # Filter by search query (name or last message content)
        if q and q.strip():
            q_lower = q.strip().lower()
            result = [
                r for r in result
                if q_lower in (r.get("name") or "").lower()
                or q_lower in ((r.get("lastMessage") or {}).get("content", "")).lower()
            ]

        # Sort by recent activity: last message time, then connection time
        result.sort(key=lambda r: (
            r["lastMessage"]["created_at"] if r.get("lastMessage") else connected_at_map.get(r["id"], ""),
        ), reverse=True)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get_connections: {type(e).__name__}: {e}")


@router.post("/fetchJobs", response_model=Dict[str, Any])
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
            ),
            companies!company_id(name, photo)
        """)

        role = filters.get("role")
        experience = filters.get("experience")
        country = filters.get("country")
        city = filters.get("city")
        salary = filters.get("salary")
        bookmarked = filters.get("bookmarked")
        search = filters.get("search")
        cursor = filters.get("cursor")
        batch_size = filters.get("batch_size") or FETCH_BATCH_SIZE

        accepted_job_ids = []
        bookmark_ids = []

        if user:
            accepted_res = supabase.table("user_job_actions") \
                .select("job_id") \
                .eq("user_id", user["id"]) \
                .eq("action", "accepted") \
                .execute()
            accepted_job_ids = [a["job_id"] for a in (accepted_res.data or [])]

            if bookmarked:
                bookmark_res = supabase.table("user_job_actions") \
                    .select("job_id") \
                    .eq("user_id", user["id"]) \
                    .eq("action", "bookmark") \
                    .execute()
                bookmark_ids = [b["job_id"] for b in (bookmark_res.data or [])]
        # --------------------------
        # 2. Filtering logic
        # --------------------------

        # Search → broad match across main fields + related tables
        if search and search.strip():
            q = search.strip()
            search_ids = set()

            main_res = supabase.table("jobs").select("id").or_(
                f"headline.ilike.%{q}%,"
                f"subheadline.ilike.%{q}%,"
                f"organization.ilike.%{q}%,"
                f"location.ilike.%{q}%"
            ).execute()
            for r in (main_res.data or []):
                search_ids.add(r["id"])

            hl_res = supabase.table("job_highlights").select("job_id").ilike("highlight", f"%{q}%").execute()
            for r in (hl_res.data or []):
                search_ids.add(r["job_id"])

            tag_res = supabase.table("job_tags").select("job_id").ilike("tag", f"%{q}%").execute()
            for r in (tag_res.data or []):
                search_ids.add(r["job_id"])

            item_res = supabase.table("job_section_items").select("section_id").ilike("item", f"%{q}%").execute()
            sec_ids_with_match = [r["section_id"] for r in (item_res.data or [])]
            if sec_ids_with_match:
                sec_res = supabase.table("job_sections").select("job_id").in_("id", sec_ids_with_match).execute()
                for r in (sec_res.data or []):
                    search_ids.add(r["job_id"])

            if not search_ids:
                return []
            query = query.in_("id", list(search_ids))

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

        # Filter to bookmarked only
        if bookmarked:
            if not bookmark_ids:
                return []
            query = query.in_("id", bookmark_ids)

        # Count total matching rows (before cursor/limit)
        total_count = 0
        count_query = supabase.table("jobs").select("id")
        if role:
            count_query = count_query.or_(f"headline.ilike.%{role}%,subheadline.ilike.%{role}%,intro.ilike.%{role}%")
        if experience is not None:
            count_query = count_query.lte("experience", experience)
        if country:
            countries_ct = [c.strip() for c in country.split(",") if c.strip()]
            if countries_ct:
                count_query = count_query.or_(",".join([f"location.ilike.%{c}%" for c in countries_ct]))
        if city:
            cities_ct = [c.strip() for c in city.split(",") if c.strip()]
            if cities_ct:
                count_query = count_query.or_(",".join([f"location.ilike.%{c}%" for c in cities_ct]))
        if salary is not None:
            count_query = count_query.lte("salary", salary)
        if accepted_job_ids:
            count_query = count_query.not_.in_("id", accepted_job_ids)
        if bookmarked:
            if bookmark_ids:
                count_query = count_query.in_("id", bookmark_ids)
        if search and search.strip():
            count_query = count_query.in_("id", list(search_ids))
        count_result = count_query.execute()
        total_count = len(count_result.data or [])

        # --------------------------
        # 3. Pagination
        # --------------------------
        if cursor:
            c = supabase.table("jobs").select("created_at, id").eq("id", cursor).single().execute()
            if c.data:
                cursor_time = c.data["created_at"]
                query = query.or_(
                    f"created_at.lt.{cursor_time},"
                    f"and(created_at.eq.{cursor_time},id.lt.{cursor})"
                )

        query = query.order("created_at", desc=True).order("id", desc=True).limit(batch_size + 1)

        # --------------------------
        # 4. Fetch jobs
        # --------------------------

        jobs_res = query.execute()

        jobs = jobs_res.data or []

        has_more = len(jobs) > batch_size
        if has_more:
            jobs.pop()

        if not jobs:
            return {"items": [], "next_cursor": None, "has_more": False, "total_count": total_count}

        # --------------------------
        # 5. Grouping
        # --------------------------
        result = []

        for job in jobs:
            result.append({
                "id": job["id"],
                "kind": "jobs",
                "headline": job.get("headline"),
                "subheadline": job.get("companies", {}).get("name") if isinstance(job.get("companies"), dict) else job.get("subheadline"),
                "companyPhoto": job.get("companies", {}).get("photo") if isinstance(job.get("companies"), dict) else None,
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

        return {
            "items": result,
            "next_cursor": result[-1]["id"] if has_more else None,
            "has_more": has_more,
            "total_count": total_count,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fetch_jobs: {type(e).__name__}: {e}")


@router.get("/jobApplications")
def job_applications(user: dict = Depends(get_current_user)):
    try:
        actions_res = supabase.table("user_job_actions") \
            .select("job_id, status") \
            .eq("user_id", user["id"]) \
            .execute()

        job_ids = [a["job_id"] for a in (actions_res.data or [])]
        status_map = {a["job_id"]: a.get("status", "new") for a in (actions_res.data or [])}

        if not job_ids:
            return []

        jobs_res = supabase.table("jobs").select("""
            *,
            job_highlights(highlight),
            job_tags(tag),
            job_sections(id, title, job_section_items(item))
        """).in_("id", job_ids).execute()

        jobs = jobs_res.data or []

        result = []
        for job in jobs:
            result.append({
                "id": job["id"],
                "kind": "jobs",
                "status": status_map.get(job["id"], "new"),
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
        raise HTTPException(status_code=500, detail=f"job_applications: {type(e).__name__}: {e}")


@router.post("/jobAction")
def accept_job(payload: Dict[str, str], user: str = Depends(get_current_user)):

    job_id = payload.get("jobId")
    action = payload.get("action", "accepted")

    if not user or not job_id:
        raise HTTPException(status_code=400, detail="Missing fields")

    try:
        supabase.table("user_job_actions").upsert({
            "user_id": user["id"],
            "job_id": job_id,
            "action": action,
        }).execute()

        return {"message": "Job action recorded"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"job_action: {type(e).__name__}: {e}")

@router.post("/peopleAction")
def connect_people(payload: Dict[str, str], user: dict = Depends(get_current_user)):

    people_id = payload.get("peopleId")
    action = payload.get("action", "accepted")

    if not user or not people_id:
        raise HTTPException(status_code=400, detail="Missing fields")

    try:
        # Non-standard actions (e.g. bookmark) just upsert and return
        if action != "accepted":
            supabase.table("user_people_actions").upsert({
                "user_id": user["id"],
                "people_id": people_id,
                "action": action,
            }).execute()
            return {"message": "Action recorded"}

        # 1. Check if the other person already sent a request to me
        reverse_res = supabase.table("user_people_actions") \
            .select("*") \
            .eq("user_id", people_id) \
            .eq("people_id", user["id"]) \
            .execute()

        reverse_exists = reverse_res.data and len(reverse_res.data) > 0

        if reverse_exists:
            # 2. Mutual connection found → update both to "connected"
            supabase.table("user_people_actions").upsert({
                "user_id": user["id"],
                "people_id": people_id,
                "action": "connected"
            }).execute()

            supabase.table("user_people_actions").update({
                "action": "connected"
            }).eq("user_id", people_id) \
             .eq("people_id", user["id"]) \
             .execute()

            # Create conversation and add both participants
            conv = supabase.table("conversations").insert({}).execute()
            if conv.data:
                conversation_id = conv.data[0]["id"]
                supabase.table("conversation_participants").insert([
                    {"conversation_id": conversation_id, "user_id": user["id"]},
                    {"conversation_id": conversation_id, "user_id": people_id},
                ]).execute()

            other_person = supabase.table("people").select("headline, name").eq("id", people_id).single().execute()
            other_name = other_person.data.get("headline") or other_person.data.get("name") or "Someone" if other_person.data else "Someone"
            my_name = user.get("headline") or user.get("name") or "Someone"

            send_push(
                people_id,
                f"You connected with {my_name}",
                "Start a conversation and see where it goes.",
                {"type": "connection", "peopleId": user["id"]},
            )
            send_push(
                user["id"],
                f"You connected with {other_name}",
                "Start a conversation and see where it goes.",
                {"type": "connection", "peopleId": people_id},
            )

            return {
                "message": "It's a match! You are now connected",
                "matched": True,
                "conversationId": conv.data[0]["id"] if conv.data else None,
            }

        else:
            # 3. Normal request
            supabase.table("user_people_actions").upsert({
                "user_id": user["id"],
                "people_id": people_id,
                "action": "sent"
            }).execute()

            return {"message": "Connection request sent", "matched": False}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"people_action: {type(e).__name__}: {e}")


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
                err = (person_insert.error or {}).get("message", "unknown")
                raise HTTPException(status_code=500, detail=f"insert_people: insert failed — {err}")

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
                    err = (section_insert.error or {}).get("message", "unknown")
                    raise HTTPException(status_code=500, detail=f"insert_people: section insert failed — {err}")
                section_id = section_insert.data[0]["id"]
                items = section.get("items") or []
                if items:
                    supabase.table("people_section_items").insert([
                        {"section_id": section_id, "item": item}
                        for item in items
                    ]).execute()

        return {"message": "People inserted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert_people: {type(e).__name__}: {e}")


@router.post("/sendMessage")
def send_message(payload: Dict[str, str], user: dict = Depends(get_current_user)):
    recipient_id = payload.get("recipientId")
    content = payload.get("content")

    if not recipient_id or not content:
        raise HTTPException(status_code=400, detail="Missing recipientId or content")

    try:
        # Check recipient's messaging preference
        recipient_pref = supabase.table("people").select("allow_messages_from") \
            .eq("id", recipient_id).single().execute()
        if recipient_pref.data:
            pref = recipient_pref.data.get("allow_messages_from", "all")
            if pref == "none":
                raise HTTPException(status_code=403, detail="This user is not accepting messages")
            if pref == "connections":
                conn_check = supabase.table("user_people_actions").select("id") \
                    .or_(
                        f"and(user_id.eq.{user['id']},people_id.eq.{recipient_id},action.eq.connected),"
                        f"and(user_id.eq.{recipient_id},people_id.eq.{user['id']},action.eq.connected)"
                    ).limit(1).execute()
                if not conn_check.data:
                    raise HTTPException(status_code=403, detail="You must be connected to message this user")

        # Find existing conversation between the two users
        my_convs = supabase.table("conversation_participants") \
            .select("conversation_id") \
            .eq("user_id", user["id"]) \
            .execute()

        my_conv_ids = [c["conversation_id"] for c in (my_convs.data or [])]

        conversation_id = None
        if my_conv_ids:
            their_conv = supabase.table("conversation_participants") \
                .select("conversation_id") \
                .eq("user_id", recipient_id) \
                .in_("conversation_id", my_conv_ids) \
                .maybe_single() \
                .execute()

            if their_conv.data:
                conversation_id = their_conv.data["conversation_id"]

        # Create new conversation if none exists
        if not conversation_id:
            conv = supabase.table("conversations").insert({}).execute()
            if not conv.data:
                err = (conv.error or {}).get("message", "unknown")
                raise HTTPException(status_code=500, detail=f"send_message: create conversation failed — {err}")
            conversation_id = conv.data[0]["id"]

            supabase.table("conversation_participants").insert([
                {"conversation_id": conversation_id, "user_id": user["id"]},
                {"conversation_id": conversation_id, "user_id": recipient_id},
            ]).execute()

        # Insert the message
        msg = supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "sender_id": user["id"],
            "content": content,
        }).execute()

        if not msg.data:
            err = (msg.error or {}).get("message", "unknown")
            raise HTTPException(status_code=500, detail=f"send_message: insert message failed — {err}")

        # Update conversation timestamp
        supabase.table("conversations").update({
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", conversation_id).execute()

        sender_name = user.get("headline") or user.get("name") or "Someone"
        content_preview = (content[:120] + "…") if len(content) > 120 else content
        send_push(
            recipient_id,
            sender_name,
            content_preview,
            {"type": "message", "conversationId": conversation_id},
        )

        return {
            "message": "Message sent",
            "conversationId": conversation_id,
            "msg": msg.data[0],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"send_message: {type(e).__name__}: {e}")


@router.post("/getMessages")
def get_messages(payload: Dict[str, str], user: dict = Depends(get_current_user)):
    conversation_id = payload.get("conversationId")
    recipient_id = payload.get("recipientId")

    if not conversation_id and not recipient_id:
        raise HTTPException(status_code=400, detail="Provide conversationId or recipientId")

    try:
        if not conversation_id and recipient_id:
            my_convs = supabase.table("conversation_participants") \
                .select("conversation_id") \
                .eq("user_id", user["id"]) \
                .execute()

            my_conv_ids = [c["conversation_id"] for c in (my_convs.data or [])]

            if my_conv_ids:
                their_conv = supabase.table("conversation_participants") \
                    .select("conversation_id") \
                    .eq("user_id", recipient_id) \
                    .in_("conversation_id", my_conv_ids) \
                    .maybe_single() \
                    .execute()

                if their_conv.data:
                    conversation_id = their_conv.data["conversation_id"]

        if not conversation_id:
            return []

        messages_res = supabase.table("messages") \
            .select("id, sender_id, content, created_at") \
            .eq("conversation_id", conversation_id) \
            .order("created_at") \
            .execute()

        return messages_res.data or []

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get_messages: {type(e).__name__}: {e}")
