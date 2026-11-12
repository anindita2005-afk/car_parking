# 🅿️ ParkIQ - AI-Powered Multi-Floor Parking Management System

**ParkIQ** is an end-to-end intelligent parking and facility management platform featuring a real-time **2D Digital Twin World Model**, **Computer Vision Telemetry (YOLOv8 + EasyOCR ANPR)**, **Level-Wise Proximity Slot Allocation**, and **A\* Multi-Floor Navigation**.

---

## 🚀 Key Highlights & Capabilities

- 🏢 **Multi-Floor Digital Twin (56 Bays)**: Real-time interactive 2D canvas visualization covering Floor 1 and Floor 2 with seamless inter-floor ramp navigation (`SLOPE UP F1→F2` and `SLOPE DOWN F2→F1`).
- 🤖 **Computer Vision & ANPR**: YOLOv8 vehicle detection, ByteTrack tracking, and EasyOCR automated number-plate recognition with confidence scoring and telemetry stream.
- 🎯 **Level-Wise Deterministic Allocation**: Intelligent priority-based slot assignment ordering filling bays level-by-level (Row 1 $\to$ Row 6 $\to$ Crossroad) based on roadway distance and aisle accessibility.
- 🧭 **A\* Pathfinding & Turn Navigation**: Orthogonal driving paths and ramp traversal with waypoint animations for entering and exiting vehicles.
- 💳 **Live Billing & Tariff Analytics**: Automated duration tracking and billing (₹20 / 30-min block) with real-time collected revenue metrics and session history.
- 🎮 **Interactive Simulation Dispatcher**: Built-in test dispatcher to simulate vehicle entry, auto-park in bay, vehicle exit (payment), and quick facility reset.

---

## 🏗️ System Architecture

```
car-parking/
├── backend/                  # FastAPI REST API & Central State Engine
│   ├── app/
│   │   ├── allocation/       # Intelligent Slot Allocation & Priority Graph
│   │   ├── api/              # Endpoints (/state, /entry, /exit, /simulate-event, /reset)
│   │   ├── core/             # StateEngine, Database & Session Lifecycles
│   │   ├── models/           # SQLAlchemy 2.0 Declarative Models
│   │   ├── navigation/       # A* Multi-Floor Graph Router
│   │   └── schemas/          # Pydantic Schemas
│   └── requirements.txt
├── frontend/                 # Interactive Web UI & Digital Twin
│   ├── app.js                # Canvas Digital Twin Engine & Real-Time Client
│   ├── index.html            # Dashboard HUD, Telemetry & KPI Cards
│   └── style.css             # Glassmorphism Styling
├── cv-engine/                # Computer Vision & Automated License Plate Recognition
│   ├── anpr/                 # EasyOCR Text Recognition & Normalizer
│   ├── detection/            # YOLOv8 Vehicle Detector
│   ├── occupancy/            # Polygon IoU Slot Occupancy Manager
│   └── tracking/             # ByteTrack Multi-Object Tracking State
├── tests/                    # System Validation & Integration Test Suite
│   └── test_system_suite.py  # Automated Test Suite (13 passing tests)
├── yolov8n.pt                # YOLOv8 Neural Network Weights
└── start_system.bat          # One-Click Launch Script
```

---

## 🛠️ Quick Start

### Prerequisites
- **Python 3.10+**
- **Node.js 18+** & npm

### 1. Start the Complete System (One-Click)
On Windows, simply run:
```bat
start_system.bat
```
This automatically launches:
1. **Backend Server**: `http://127.0.0.1:8000` (FastAPI + Swagger Docs at `/docs`)
2. **Frontend UI**: `http://localhost:5173` (Vite / Vanilla JS)

---

### 2. Manual Startup

#### Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate       # On Windows (or source venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## 🧪 Testing & Verification

Run the comprehensive automated test suite:
```bash
python -m unittest tests/test_system_suite.py
```

Run static type checks via Pyrefly:
```bash
pyrefly check "backend/app" "tests"
```

---

## 📜 License
MIT License. Built for modern intelligent transportation systems.

