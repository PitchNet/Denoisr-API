from fastapi import FastAPI
from app.controllers import LoginController, FeedController
from fastapi.middleware.cors import CORSMiddleware
from db import supabase

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(LoginController.router)
app.include_router(FeedController.router)