from fastapi import APIRouter
from app.services.service import greet_user

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/{name}")
def say_hello(name: str):
    return {"message": greet_user(name)}
