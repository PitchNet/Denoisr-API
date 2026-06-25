from typing import Any


def assemble_children(row: dict, prefix: str) -> tuple[list, list, list]:
    """Flatten the nested highlights/tags/sections children of a people/job row.

    `prefix` is "people" or "job". Reads the nested-select children already
    present on `row` (e.g. row["people_highlights"]) and returns
    `(highlights, tags, sections)` where sections is `[{"title", "items"}]`.
    Centralises the assembly previously copy-pasted across the feed, profile,
    and company controllers.
    """
    highlights = [h["highlight"] for h in row.get(f"{prefix}_highlights", []) if "highlight" in h]
    tags = [t["tag"] for t in row.get(f"{prefix}_tags", []) if "tag" in t]
    sections = [
        {
            "title": s.get("title"),
            "items": [i["item"] for i in s.get(f"{prefix}_section_items", []) if "item" in i],
        }
        for s in row.get(f"{prefix}_sections", [])
    ]
    return highlights, tags, sections


def api_error(e: Exception, operation: str = "") -> dict[str, Any]:
    """Build a richer error detail from an exception.

    For Supabase errors the detail was often opaque; including the
    exception type name makes it possible to tell a missing table
    from a network timeout from a constraint violation.
    """
    msg = str(e) or repr(e)
    return {"detail": f"{operation}: {type(e).__name__}: {msg}" if operation else f"{type(e).__name__}: {msg}"}


def check_data(response: Any, label: str) -> None:
    """Raise 500 with a useful message when a Supabase response has no data."""
    from fastapi import HTTPException
    if response.data:
        return
    err = response.error or {}
    msg = err.get("message", "No data returned")
    code = err.get("code", "")
    suffix = f" (code={code})" if code else ""
    raise HTTPException(status_code=500, detail=f"{label}: {msg}{suffix}")
