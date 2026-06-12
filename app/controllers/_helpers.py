from typing import Any

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
