from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import time
from app.core.state_engine import state_engine
from app.navigation.router import ParkingRouter
from app.services.car_detector import car_detector

router = APIRouter()
router_engine = ParkingRouter()

class VehicleEntryPayload(BaseModel):
    plate_number: str
    vehicle_type: Optional[str] = "car"
    is_ev: Optional[bool] = False
    track_id: Optional[int] = None
    camera_id: Optional[str] = "CAM_01"
    confidence: Optional[float] = 1.0
    ocr_confidence: Optional[float] = 1.0

class OccupancyUpdatePayload(BaseModel):
    camera_id: Optional[str] = "CAM_01"
    slots: Dict[str, Dict[str, Any]]

class RouteRequestPayload(BaseModel):
    start_node: Optional[str] = "ENTRANCE"
    target_slot: str
    blocked_nodes: Optional[List[str]] = []

@router.get("/state")
def get_parking_state():
    """
    Returns full authoritative real-time Digital Twin state.
    """
    return state_engine.get_summary_state()

@router.post("/entry")
def process_vehicle_entry(payload: VehicleEntryPayload):
    """
    CV / Gate Vehicle Entry endpoint:
    Performs AI allocation, computes A* route, logs event, and updates state.
    """
    session = state_engine.record_entry(
        plate_number=payload.plate_number,
        vehicle_type=payload.vehicle_type,
        is_ev=payload.is_ev,
        track_id=payload.track_id,
        camera_id=payload.camera_id,
        ocr_conf=payload.ocr_confidence
    )
    return session

@router.post("/upload-vehicle")
async def upload_and_detect_vehicle(file: UploadFile = File(...)):
    """
    Accepts an uploaded car image (or video), runs YOLOv8 vehicle detection + ANPR OCR,
    registers the vehicle into the authoritative parking allocation state engine,
    and returns detection metadata, assigned parking bay, A* route coordinates, and telemetry.
    """
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    
    # Process with YOLOv8 & ANPR
    try:
        detection = car_detector.detect_and_process(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Detection error: {str(e)}")

    plate_number = detection["plate_number"]
    vehicle_type = detection["vehicle_type"]
    is_ev = detection["is_ev"]
    ocr_conf = detection["ocr_confidence"]
    track_id = int(time.time() * 1000) % 900 + 100

    # Record entry into state engine & digital twin
    session = state_engine.record_entry(
        plate_number=plate_number,
        vehicle_type=vehicle_type,
        is_ev=is_ev,
        track_id=track_id,
        camera_id="CAM_UPLOAD",
        ocr_conf=ocr_conf
    )

    state_engine.log_event(
        event_type="YOLO_ENTRY",
        message=f"🚗 Vehicle {plate_number} ({vehicle_type.upper()}) detected by YOLOv8n (conf: {detection['confidence']*100:.0f}%). Assigned to {session.get('assigned_slot') or 'EXIT'}.",
        details={"plate": plate_number, "slot": session.get("assigned_slot"), "confidence": detection["confidence"]}
    )

    return {
        "status": "success",
        "detection": detection,
        "session": session,
        "assigned_slot": session.get("assigned_slot"),
        "route": session.get("route")
    }

@router.post("/occupancy")
def update_cv_occupancy(payload: OccupancyUpdatePayload):
    """
    Called by CV Engine to update slot statuses in real-time.
    """
    state_engine.update_occupancy_from_cv(payload.slots)
    return {"status": "success", "updated_slots": len(payload.slots)}

@router.post("/exit")
def process_vehicle_exit(plate_or_track_id: str = Query(..., description="Plate number or tracking ID")):
    """
    Processes vehicle exit, vacates slot, and closes active session.
    """
    session = state_engine.record_exit(plate_or_track_id)
    if not session:
        raise HTTPException(status_code=404, detail="Active vehicle session not found")
    return {"status": "success", "session": session}

@router.post("/route")
def calculate_route(payload: RouteRequestPayload):
    """
    A* / Dijkstra route calculation between arbitrary waypoints/slots.
    """
    route = router_engine.find_shortest_path(
        start=payload.start_node or "ENTRANCE",
        target=payload.target_slot,
        blocked_nodes=set(payload.blocked_nodes or [])
    )
    return route

@router.get("/analytics")
def get_parking_analytics():
    """
    Provides predictive parking analytics and occupancy metrics.
    """
    summary = state_engine.get_summary_state()
    kpis = summary["kpis"]
    total = kpis["total_capacity"]
    occ = kpis["occupied"]
    rate = kpis["occupancy_rate"]

    # Predictive demand estimates based on current occupancy trends
    predicted_next_hour_demand = min(100.0, max(10.0, rate * 1.15))
    peak_probability = "HIGH" if rate > 70 else ("MODERATE" if rate > 40 else "LOW")

    return {
        "current_occupancy_rate": rate,
        "predicted_next_hour_demand_pct": round(predicted_next_hour_demand, 1),
        "peak_probability": peak_probability,
        "general_utilization": f"{sum(1 for s in summary['slots'].values() if s['status'] == 'OCCUPIED')}/{len(summary['slots'])}",
        "turnover_today": kpis["total_vehicles_today"]
    }

@router.post("/simulate-event")
def trigger_simulation_event(action: str = "entry", target: Optional[str] = None, floor: Optional[int] = None):
    """
    Deterministic simulation trigger for testing and demonstration.
    Uses the EXACT same allocation and digital twin state engine.
    Supports targeting a specific slot, floor (1 or 2), or plate for entry & exit action.
    """
    import random
    if action == "entry":
        active_plates = {s.get("plate_number") for s in state_engine.sessions if s.get("status") != "COMPLETED"}
        active_plates.update({slot.get("vehicle_plate") for slot in state_engine.slots.values() if slot.get("vehicle_plate")})

        # Generate a unique plate not currently inside the facility (General standard vehicles)
        state_prefixes = ["DL", "MH", "KA", "WB", "TN", "TS", "GJ", "UP", "HR"]
        series = ["AB", "CD", "EF", "GH", "JK", "MN", "PQ", "RS", "XY", "ZZ"]
        
        plate_candidate = f"{random.choice(state_prefixes)}{random.randint(1, 99):02d}{random.choice(series)}{random.randint(1000, 9999)}"
        vehicle_type = "general"
        is_ev = False

        # Ensure uniqueness
        for _ in range(20):
            if plate_candidate not in active_plates:
                break
            plate_candidate = f"{random.choice(state_prefixes)}{random.randint(1, 99):02d}{random.choice(series)}{random.randint(1000, 9999)}"

        session = state_engine.record_entry(
            plate_number=plate_candidate,
            vehicle_type=vehicle_type,
            is_ev=is_ev,
            track_id=random.randint(100, 999),
            camera_id="CAM_SIM",
            ocr_conf=round(random.uniform(0.92, 0.99), 2),
            preferred_floor=floor,
            target_slot=target
        )
        return {"action": "entry", "session": session}
    elif action == "park":
        result = state_engine.record_park(target=target, floor=floor)
        return result
    elif action == "exit":
        result = state_engine.record_exit(plate_or_track_id=target, floor=floor)
        if result:
            return {
                "action": "exit",
                "target": target,
                "floor": result.get("floor", floor or 1),
                "plate": result.get("plate_number"),
                "result": result
            }
        floor_msg = f" on Floor {floor}" if floor else ""
        return {"action": "exit", "status": "no_vehicle", "message": f"No active vehicle to exit{floor_msg}"}
        
    return {"status": "unknown action"}

@router.post("/reset")
def reset_facility_state():
    """
    Resets the entire digital twin facility: all 56 bays set to General Free.
    """
    return state_engine.reset_facility()

@router.get("/db/slots")
def get_database_slots():
    """
    Returns all parking slots / plots from the SQLite database table
    with their real-time statuses (FREE, OCCUPIED, RESERVED, ALLOCATED, RESTRICTED).
    """
    slots = state_engine.get_db_slots_data()
    return {
        "table": "parking_slots",
        "total_slots": len(slots),
        "free_count": sum(1 for s in slots if s["status"] == "FREE"),
        "occupied_count": sum(1 for s in slots if s["status"] == "OCCUPIED"),
        "allocated_count": sum(1 for s in slots if s["status"] == "ALLOCATED"),
        "reserved_count": sum(1 for s in slots if s["status"] == "RESERVED"),
        "slots": slots
    }

@router.get("/db/sessions")
def get_database_sessions(limit: int = 100):
    """
    Returns all vehicle parking sessions stored in the SQLite database table,
    including license plates, entry time, exit time, assigned slot, duration, and fee.
    """
    sessions = state_engine.get_db_sessions_data(limit=limit)
    return {
        "table": "parking_sessions",
        "total_records": len(sessions),
        "sessions": sessions
    }


