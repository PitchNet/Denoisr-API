from fastapi import FastAPI
from app.controllers import LoginController

app = FastAPI()

# Register routers
app.include_router(LoginController.router)