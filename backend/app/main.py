import os
import sys

# Ensure backend root is on Python path
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.api.endpoints import router as api_router
from app.core.database import engine, Base

# Initialize DB tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Intelligent Parking Management System API",
    description="Backend API and Real-Time Digital Twin for Computer Vision Parking System",
    version="2.0.0"
)

# Enable CORS for local web dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

# Mount frontend directory for direct dashboard serving
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
if os.path.exists(FRONTEND_DIR):
    app.mount("/dashboard", StaticFiles(directory=FRONTEND_DIR, html=True), name="dashboard")

@app.get("/")
def root():
    # If dashboard exists, redirect directly to dashboard
    if os.path.exists(FRONTEND_DIR):
        return RedirectResponse(url="/dashboard/index.html")
    return {
        "system": "Intelligent Parking Management System (IPMS)",
        "status": "ONLINE",
        "api_docs": "/docs",
        "dashboard": "/dashboard/index.html"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, app_dir=BACKEND_ROOT)

