import os
from fastapi import FastAPI
from app.controllers import LoginController, FeedController, ProfileController, CompanyController
from fastapi.middleware.cors import CORSMiddleware
from db import supabase

app = FastAPI()

origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,https://denoisr-ui.vercel.app").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(LoginController.router)
app.include_router(FeedController.router)
app.include_router(ProfileController.router)
app.include_router(CompanyController.router)