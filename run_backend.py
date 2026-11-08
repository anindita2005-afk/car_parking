import os
import sys

# Add backend to Python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 65)
    print("  [PARKIQ BACKEND SERVER] (YOLOv8 + ANPR + DIGITAL TWIN)")
    print(f"  Root Dir: {ROOT_DIR}")
    print(f"  Backend Dir: {BACKEND_DIR}")
    print("  Dashboard URL: http://localhost:8000/dashboard/index.html")
    print("  API Docs URL:  http://localhost:8000/docs")
    print("=" * 65 + "\n")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, app_dir=BACKEND_DIR)
