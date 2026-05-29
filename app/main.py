from fastapi import FastAPI
from app.controllers import LoginController, FeedController, ProfileController
from fastapi.middleware.cors import CORSMiddleware
from db import supabase

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(LoginController.router)
app.include_router(FeedController.router)
app.include_router(ProfileController.router)