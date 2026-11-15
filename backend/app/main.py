import os
import sys

# Ensure backend root is on Python path
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import router as api_router
from app.core.database import engine, Base

# Initialize DB tables
Base.metadata.create_all(bind=engine)
# Updated router reload timestamp: 2026-11-14 exit-line-detection-and-tariff

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

@app.on_event("startup")
def warmup_cv_pipeline():
    """Non-blocking background thread to pre-warm YOLO and EasyOCR models on startup."""
    import threading
    def _warmup():
        try:
            from app.services.car_detector import car_detector
            car_detector._get_ocr_reader()
        except Exception:
            pass
    threading.Thread(target=_warmup, daemon=True).start()

@app.get("/")
def root():
    return {
        "system": "Intelligent Parking Management System (IPMS) Backend API",
        "status": "ONLINE",
        "api_docs": "/docs",
        "frontend": "http://localhost:5173"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, app_dir=BACKEND_ROOT)

