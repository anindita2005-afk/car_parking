import time
import math
import json
import os
import uuid
from datetime import datetime
from sqlalchemy import func
from app.allocation.engine import SlotAllocator
from app.navigation.router import ParkingRouter
from app.core.database import SessionLocal, engine, Base
from app.models.parking import ParkingSlot, ParkingSession, SystemLog

class ParkingStateEngine:
    """
    Central Authoritative State Engine for the Digital Twin & Database Synchronization.
    Persists vehicle license plates, entry/exit timestamps, slot allocations, and slot statuses
    (FREE, OCCUPIED, RESERVED, ALLOCATED, RESTRICTED) to SQLite via SQLAlchemy.
    """
    def __init__(self):
        self.allocator = SlotAllocator()
        self.router = ParkingRouter()
        self.rate_per_30_mins = 20 # ₹20 per 30 minutes
        self.total_revenue_inr = 0 # Total revenue collected
        
        # Initialize DB tables
        Base.metadata.create_all(bind=engine)

        self.slots = {}
        self.active_vehicles = {}     # track_id/plate -> vehicle telemetry
        self.sessions = []            # list of recent sessions
        self.activity_feed = []       # list of log events
        self.violations = []          # list of violation alerts
        self.total_vehicles_today = 0
        self.last_cv_frame = None

        # Synchronize database tables & initialize slots
        self._init_and_sync_db()

    def _init_and_sync_db(self):
        """
        Seeds parking slots table with all 28 bays on startup if empty,
        and synchronizes in-memory digital twin with database records.
        """
        db = SessionLocal()
        try:
            # Check existing slots in DB
            db_slots = db.query(ParkingSlot).all()
            if not db_slots:
                print("[StateEngine] Seeding 56 General Parking Slots into SQLite Database...")
                for slot_id, meta in self.allocator.slots_metadata.items():
                    slot_num = int(slot_id.replace("S", "")) if slot_id.startswith("S") and slot_id[1:].isdigit() else None
                    slot_type = "GENERAL"
                    default_status = "FREE"
                    
                    new_slot = ParkingSlot(
                        id=slot_id,
                        slot_number=slot_num,
                        slot_type=slot_type,
                        status=default_status,
                        current_vehicle_plate=None,
                        current_track_id=None,
                        is_ev=False,
                        distance_score=meta.get("distance_score", 80),
                        x=meta.get("x", 0),
                        y=meta.get("y", 0),
                        width=meta.get("width", 80),
                        height=meta.get("height", 120)
                    )
                    db.add(new_slot)
                db.commit()
                db_slots = db.query(ParkingSlot).all()
            else:
                # Sync existing slots with allocator metadata (distance_score)
                for s in db_slots:
                    meta = self.allocator.slots_metadata.get(s.id, {})
                    if "distance_score" in meta:
                        s.distance_score = meta["distance_score"]
                db.commit()

            # Populate in-memory slot map
            for s in db_slots:
                meta = self.allocator.slots_metadata.get(s.id, {})
                floor_val = getattr(s, "floor", 1) or (1 if "F1" in str(s.id) else (2 if "F2" in str(s.id) else 1))
                bay_code = meta.get("bay_code") or (s.id.split("-")[-1] if "-" in str(s.id) else str(s.id))
                self.slots[s.id] = {
                    "id": s.id,
                    "floor": floor_val,
                    "bay_code": bay_code,
                    "slot_number": s.slot_number,
                    "type": "GENERAL",
                    "status": "AVAILABLE" if s.status == "FREE" else s.status,
                    "vehicle_plate": s.current_vehicle_plate,
                    "track_id": s.current_track_id,
                    "distance_score": getattr(s, "distance_score", 50),
                    "entry_time": s.occupied_since.strftime("%H:%M:%S") if s.occupied_since else None,
                    "entry_timestamp": s.occupied_since.timestamp() if s.occupied_since else None,
                    "x": meta.get("x", s.x),
                    "y": meta.get("y", s.y),
                    "width": meta.get("width", s.width),
                    "height": meta.get("height", s.height),
                    "orientation": meta.get("orientation", "vertical"),
                    "accent_color": meta.get("accent_color", "green"),
                    "is_ev": False
                }

            # Load active sessions from DB
            active_db_sessions = db.query(ParkingSession).filter(
                ParkingSession.status.in_(["ENTERING", "PARKED", "ACTIVE", "BYPASS"])
            ).order_by(ParkingSession.id.desc()).all()

            for s in active_db_sessions:
                sess_obj = {
                    "session_id": s.session_id,
                    "plate_number": s.vehicle_plate,
                    "vehicle_type": s.vehicle_type,
                    "is_ev": s.is_ev,
                    "track_id": s.track_id,
                    "camera_id": s.camera_id,
                    "entry_timestamp": s.entry_timestamp,
                    "entry_time": s.entry_time.strftime("%Y-%m-%d %H:%M:%S") if s.entry_time else time.strftime("%Y-%m-%d %H:%M:%S"),
                    "status": s.status,
                    "assigned_slot": s.assigned_slot,
                    "allocation_reason": "Loaded from Database",
                    "route": json.loads(str(s.route_json)) if s.route_json else None,
                    "ocr_confidence": round(float(getattr(s, "ocr_confidence", 1.0) or 1.0) * 100, 1),
                    "fee_inr": float(getattr(s, "fee_inr", self.rate_per_30_mins) or self.rate_per_30_mins),
                    "fee_formatted": f"₹{int(float(getattr(s, 'fee_inr', self.rate_per_30_mins) or self.rate_per_30_mins))}"
                }
                self.sessions.append(sess_obj)

            # Calculate total vehicles today
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = db.query(ParkingSession).filter(ParkingSession.created_at >= today_start).count()
            self.total_vehicles_today = today_count

            # Calculate total completed revenue today from database
            today_completed_rev = db.query(func.sum(ParkingSession.fee_inr)).filter(
                ParkingSession.status == "COMPLETED",
                ParkingSession.created_at >= today_start
            ).scalar()
            self.total_revenue_inr = int(float(today_completed_rev or 0))

        except Exception as e:
            print(f"[StateEngine] DB Sync error: {e}")
            db.rollback()
        finally:
            db.close()

    def calculate_billing(self, entry_timestamp, exit_timestamp=None):
        """
        Calculates staying duration with exact seconds/minutes/hours resolution
        and charges ₹20 per 30 minutes block.
        """
        if not entry_timestamp:
            entry_timestamp = time.time()
        if exit_timestamp is None:
            exit_timestamp = time.time()
            
        elapsed_seconds = max(0, int(exit_timestamp - entry_timestamp))
        elapsed_minutes = elapsed_seconds / 60.0
        blocks_30m = max(1, math.ceil(elapsed_seconds / 1800)) if elapsed_seconds > 0 else 1
        fee_inr = blocks_30m * self.rate_per_30_mins

        hours = elapsed_seconds // 3600
        mins = (elapsed_seconds % 3600) // 60
        secs = elapsed_seconds % 60

        if hours > 0:
            duration_str = f"{hours}h {mins:02d}m {secs:02d}s"
        elif mins > 0:
            duration_str = f"{mins}m {secs:02d}s"
        else:
            duration_str = f"{secs}s"

        return {
            "duration_seconds": elapsed_seconds,
            "duration_minutes": round(elapsed_minutes, 1),
            "duration_formatted": duration_str,
            "blocks_30m": blocks_30m,
            "rate_per_30m": self.rate_per_30_mins,
            "fee_inr": fee_inr,
            "fee_formatted": f"₹{fee_inr}"
        }

    def log_event(self, event_type, message, details=None):
        event = {
            "id": len(self.activity_feed) + 1,
            "timestamp": time.strftime("%H:%M:%S"),
            "type": event_type,
            "message": message,
            "details": details or {}
        }
        self.activity_feed.insert(0, event)
        if len(self.activity_feed) > 100:
            self.activity_feed.pop()

        # Persist log to DB asynchronously / safely
        db = SessionLocal()
        try:
            sys_log = SystemLog(
                event_type=event_type,
                message=message,
                details_json=json.dumps(details) if details else None
            )
            db.add(sys_log)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

        return event

    def record_entry(self, plate_number, vehicle_type="car", is_ev=False, track_id=None, camera_id="CAM_01", ocr_conf=1.0, preferred_floor=None, target_slot=None):
        """
        Records vehicle entry into the Digital Twin and persists session & slot status in SQLite DB.
        Supports preferred_floor (1 or 2) and explicit target_slot assignment.
        """
        plate_str = str(plate_number or "").strip().upper()
        is_ev = False
        vehicle_type = "general"

        # 1. Build occupancy map
        current_occupancy = {}
        for sid, sdata in self.slots.items():
            current_occupancy[sid] = {"status": sdata.get("status", "AVAILABLE")}

        for sess in self.sessions:
            if sess["status"] in ["ENTERING", "ACTIVE"] and sess.get("assigned_slot"):
                aslot = sess["assigned_slot"]
                if aslot in current_occupancy:
                    current_occupancy[aslot]["status"] = "ALLOCATED"

        # 2. Allocate optimal slot
        if target_slot and target_slot in self.slots and current_occupancy.get(target_slot, {}).get("status") in ["AVAILABLE", "FREE"]:
            assigned_slot = target_slot
            reason = f"Directly allocated to {target_slot} (Floor {self.slots[target_slot].get('floor', 1)})"
        else:
            if preferred_floor in [1, 2]:
                for sid, sdata in self.slots.items():
                    if sdata.get("floor") != preferred_floor:
                        current_occupancy[sid] = {"status": "UNAVAILABLE"}

            alloc_result = self.allocator.allocate(
                occupancy_map=current_occupancy,
                vehicle_type=vehicle_type,
                is_ev=is_ev,
                plate_number=plate_str
            )

            # If preferred floor is full, fallback to any available floor
            if not alloc_result and preferred_floor in [1, 2]:
                fallback_occupancy = {}
                for sid, sdata in self.slots.items():
                    fallback_occupancy[sid] = {"status": sdata.get("status", "AVAILABLE")}
                for sess in self.sessions:
                    if sess["status"] in ["ENTERING", "ACTIVE"] and sess.get("assigned_slot"):
                        aslot = sess["assigned_slot"]
                        if aslot in fallback_occupancy:
                            fallback_occupancy[aslot]["status"] = "ALLOCATED"
                alloc_result = self.allocator.allocate(
                    occupancy_map=fallback_occupancy,
                    vehicle_type=vehicle_type,
                    is_ev=is_ev,
                    plate_number=plate_str
                )

            assigned_slot = alloc_result["slot_id"] if alloc_result else None
            reason = alloc_result["reason"] if alloc_result else "Facility full - No parking slot available. Directing to EXIT."
        
        # 3. Compute A* rectilinear navigation route
        route = self.router.find_shortest_path("ENTRANCE", assigned_slot or "EXIT")
        now_ts = time.time()
        now_dt = datetime.now()

        session_status = "ENTERING" if assigned_slot else "BYPASS"
        session_id = f"SES-{int(now_ts)}-{uuid.uuid4().hex[:6].upper()}"
        session = {
            "session_id": session_id,
            "plate_number": plate_str,
            "vehicle_type": vehicle_type,
            "is_ev": is_ev,
            "track_id": track_id,
            "camera_id": camera_id,
            "entry_timestamp": now_ts,
            "entry_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": session_status,
            "assigned_slot": assigned_slot,
            "allocation_reason": reason,
            "route": route,
            "ocr_confidence": round(ocr_conf * 100, 1),
            "duration_formatted": "1m",
            "current_fee_inr": self.rate_per_30_mins if assigned_slot else 0,
            "fee_formatted": f"₹{self.rate_per_30_mins}" if assigned_slot else "₹0 (Bypass)"
        }

        self.sessions.insert(0, session)
        self.total_vehicles_today += 1

        # Update in-memory slot state
        if assigned_slot and assigned_slot in self.slots:
            self.slots[assigned_slot]["status"] = "ALLOCATED"
            self.slots[assigned_slot]["vehicle_plate"] = plate_str
            self.slots[assigned_slot]["entry_timestamp"] = now_ts
            self.slots[assigned_slot]["entry_time"] = time.strftime("%H:%M:%S")

        if track_id is not None:
            self.active_vehicles[track_id] = session

        # 4. PERSIST TO SQLITE DATABASE
        db = SessionLocal()
        try:
            db_session = ParkingSession(
                session_id=session_id,
                vehicle_plate=plate_str,
                vehicle_type=vehicle_type,
                is_ev=is_ev,
                assigned_slot=assigned_slot,
                track_id=track_id,
                camera_id=camera_id,
                entry_time=now_dt,
                entry_timestamp=now_ts,
                status=session_status,
                ocr_confidence=ocr_conf,
                route_json=json.dumps(route) if route else None,
                fee_inr=float(self.rate_per_30_mins if assigned_slot else 0)
            )
            db.add(db_session)

            # Update Slot Table in DB
            if assigned_slot:
                db_slot = db.query(ParkingSlot).filter(ParkingSlot.id == assigned_slot).first()
                if db_slot:
                    db_slot.status = "ALLOCATED"
                    db_slot.current_vehicle_plate = plate_str
                    db_slot.current_track_id = track_id
                    db_slot.occupied_since = now_dt

            db.commit()
        except Exception as e:
            print(f"[StateEngine] Error saving session to DB: {e}")
            db.rollback()
        finally:
            db.close()

        if assigned_slot:
            self.log_event("ENTRY", f"Vehicle {plate_str} entered via {camera_id}. Assigned: {assigned_slot} (Rate: ₹20/30m)", {
                "plate": plate_str,
                "is_ev": False,
                "slot": assigned_slot,
                "reason": reason
            })
        else:
            self.log_event("BYPASS", f"Facility 100% Full: Vehicle {plate_str} cannot park. Guided directly to EXIT GATE.", {
                "plate": plate_str,
                "is_ev": False,
                "slot": None,
                "reason": reason
            })

        return session

    def record_park(self, target=None, floor=None):
        """
        Marks an entering vehicle as PARKED in its assigned bay.
        Supports filtering by target (slot ID / plate number) or floor (1 or 2).
        Syncs in-memory slots, session objects, and SQLite database.
        """
        target_session = None

        # 1. Target specific slot or plate if provided
        if target:
            norm_target = self.normalize_slot_id(target)
            for s in self.sessions:
                if s.get("status") in ["ENTERING", "BYPASS"]:
                    if s.get("assigned_slot") in [target, norm_target] or s.get("plate_number") == target:
                        target_session = s
                        break

        # 2. Prioritize entering vehicle for the specified floor
        if not target_session and floor in [1, 2]:
            for s in self.sessions:
                if s.get("status") in ["ENTERING", "BYPASS"]:
                    aslot = s.get("assigned_slot")
                    slot_obj = self.slots.get(aslot)
                    if slot_obj and slot_obj.get("floor") == floor:
                        target_session = s
                        break

        # 3. Fallback: Any entering vehicle only if no specific floor was requested
        if not target_session and floor is None:
            for s in self.sessions:
                if s.get("status") in ["ENTERING", "BYPASS"]:
                    target_session = s
                    break

        if not target_session:
            floor_msg = f" on Floor {floor}" if floor else ""
            return {"action": "park", "status": "no_pending", "message": f"No vehicle currently pending parking{floor_msg}"}

        if not target_session.get("assigned_slot"):
            return {
                "action": "park",
                "status": "rejected",
                "message": f"Facility full: Vehicle {target_session.get('plate_number')} has no bay and must proceed to EXIT."
            }

        slot_id = target_session["assigned_slot"]
        plate_str = target_session.get("plate_number")
        trk_id = target_session.get("track_id")
        slot_floor = self.slots.get(slot_id, {}).get("floor", 1)

        # Update in-memory state
        if slot_id in self.slots:
            self.slots[slot_id]["status"] = "OCCUPIED"
            self.slots[slot_id]["vehicle_plate"] = plate_str
            self.slots[slot_id]["track_id"] = trk_id
            now_ts = time.time()
            if not self.slots[slot_id].get("entry_timestamp"):
                self.slots[slot_id]["entry_timestamp"] = now_ts
                self.slots[slot_id]["entry_time"] = time.strftime("%H:%M:%S")

        target_session["status"] = "PARKED"

        # Persist to SQLite DB
        db = SessionLocal()
        try:
            db_sess = db.query(ParkingSession).filter(ParkingSession.session_id == target_session["session_id"]).first()
            if db_sess:
                db_sess.status = "PARKED"

            db_slot = db.query(ParkingSlot).filter(ParkingSlot.id == slot_id).first()
            if db_slot:
                db_slot.status = "OCCUPIED"
                db_slot.current_vehicle_plate = plate_str
                db_slot.current_track_id = trk_id
                if not db_slot.occupied_since:
                    db_slot.occupied_since = datetime.now()

            db.commit()
        except Exception as e:
            print(f"[StateEngine] Error saving park event to DB: {e}")
            db.rollback()
        finally:
            db.close()

        self.log_event("PARKED", f"Vehicle {plate_str} is now parked in Bay {slot_id} (Floor {slot_floor})", {
            "plate": plate_str,
            "slot": slot_id,
            "floor": slot_floor
        })

        return {
            "action": "park",
            "status": "SUCCESS",
            "slot": slot_id,
            "floor": slot_floor,
            "plate_number": plate_str,
            "session": target_session
        }

    def normalize_slot_id(self, slot_id):
        """
        Normalizes legacy bay codes (e.g. S01) to multi-floor IDs (F1-S01).
        """
        if not slot_id or not isinstance(slot_id, str):
            return slot_id
        if slot_id in self.slots:
            return slot_id
        if f"F1-{slot_id}" in self.slots:
            return f"F1-{slot_id}"
        if f"F2-{slot_id}" in self.slots:
            return f"F2-{slot_id}"
        return slot_id

    def update_occupancy_from_cv(self, slot_occupancy_map):
        """
        Updates slot statuses from CV or Park actions, syncing both in-memory state & SQLite DB.
        """
        db = SessionLocal()
        try:
            for raw_slot_id, data in slot_occupancy_map.items():
                slot_id = self.normalize_slot_id(raw_slot_id)
                if slot_id in self.slots:
                    prev_status = self.slots[slot_id]["status"]
                    is_occ = data.get("status") in ["occupied", "OCCUPIED"]
                    new_status = "OCCUPIED" if is_occ else "AVAILABLE"
                    
                    if prev_status != new_status:
                        self.slots[slot_id]["status"] = new_status
                        self.slots[slot_id]["type"] = "GENERAL"
                        self.slots[slot_id]["is_ev"] = False
                        self.slots[slot_id]["track_id"] = data.get("vehicle_id")
                        
                        db_slot = db.query(ParkingSlot).filter(ParkingSlot.id == slot_id).first()
                        if db_slot:
                            db_slot.status = "OCCUPIED" if is_occ else "FREE"
                            db_slot.slot_type = "GENERAL"
                            db_slot.is_ev = False

                        if is_occ:
                            now_ts = time.time()
                            now_dt = datetime.now()
                            self.slots[slot_id]["entry_timestamp"] = now_ts
                            self.slots[slot_id]["entry_time"] = time.strftime("%H:%M:%S")
                            if db_slot:
                                db_slot.occupied_since = now_dt
                            self.log_event("PARKED", f"Slot {slot_id} is now OCCUPIED by vehicle #{data.get('vehicle_id') or 'UNKNOWN'}")
                        else:
                            self.slots[slot_id]["vehicle_plate"] = None
                            self.slots[slot_id]["entry_timestamp"] = None
                            self.slots[slot_id]["entry_time"] = None
                            if db_slot:
                                db_slot.current_vehicle_plate = None
                                db_slot.current_track_id = None
                                db_slot.occupied_since = None
                            self.log_event("EXIT", f"Slot {slot_id} is now VACATED and AVAILABLE")

            db.commit()
        except Exception as e:
            print(f"[StateEngine] Error updating occupancy in DB: {e}")
            db.rollback()
        finally:
            db.close()

    def record_exit(self, plate_or_track_id=None, floor=None):
        """
        Processes vehicle exit, calculates staying fee (₹20/30m), marks session COMPLETED in DB,
        and sets the parking slot status back to FREE in DB.
        Supports explicit target (plate/track_id/slot) or floor-based resolution.
        """
        found_session = None
        target_slot_id = None

        # 1. Target specific plate, track_id, or slot
        if plate_or_track_id:
            norm_target = self.normalize_slot_id(plate_or_track_id)
            for s in self.sessions:
                if s["status"] in ["ACTIVE", "ENTERING", "PARKED", "BYPASS"]:
                    if (s.get("plate_number") == plate_or_track_id or 
                        str(s.get("track_id")) == str(plate_or_track_id) or 
                        s.get("assigned_slot") == plate_or_track_id or
                        s.get("assigned_slot") == norm_target):
                        found_session = s
                        break
            if not found_session and norm_target in self.slots:
                target_slot_id = norm_target

        # 2. If no target specified, prioritize floor if provided
        if not found_session and not target_slot_id and floor in [1, 2]:
            # A) Parked session on this floor
            for s in self.sessions:
                if s.get("status") == "PARKED" and s.get("assigned_slot"):
                    slot = self.slots.get(s.get("assigned_slot"))
                    if slot and slot.get("floor") == floor:
                        found_session = s
                        break

            # B) Any OCCUPIED slot on this floor
            if not found_session:
                for sid, sdata in self.slots.items():
                    if sdata.get("status") == "OCCUPIED" and sdata.get("floor") == floor:
                        target_slot_id = sid
                        break

            # C) Any ENTERING vehicle on this floor
            if not found_session and not target_slot_id:
                for s in self.sessions:
                    if s.get("status") in ["ENTERING", "ACTIVE"]:
                        slot = self.slots.get(s.get("assigned_slot"))
                        if slot and slot.get("floor") == floor:
                            found_session = s
                            break

        # 3. Global fallbacks (only if no specific floor was requested)
        if not found_session and not target_slot_id and floor is None:
            # A) Bypass unassigned vehicle
            for s in self.sessions:
                if s.get("status") in ["BYPASS", "ENTERING"] and not s.get("assigned_slot"):
                    found_session = s
                    break

            # B) Any parked vehicle
            if not found_session:
                for s in self.sessions:
                    if s.get("status") == "PARKED" and s.get("assigned_slot"):
                        found_session = s
                        break

            # C) Any occupied slot
            if not found_session:
                for sid, sdata in self.slots.items():
                    if sdata.get("status") == "OCCUPIED":
                        target_slot_id = sid
                        break

            # D) Any entering vehicle
            if not found_session and not target_slot_id:
                for s in self.sessions:
                    if s.get("status") in ["ENTERING", "ACTIVE"]:
                        found_session = s
                        break

        # Resolve slot_id, plate, entry_timestamp
        slot_id = None
        plate = plate_or_track_id or "UNKNOWN"
        entry_ts = time.time()

        if found_session:
            slot_id = found_session.get("assigned_slot")
            plate = found_session.get("plate_number", plate)
            entry_ts = found_session.get("entry_timestamp") or entry_ts
        elif target_slot_id:
            slot_id = target_slot_id
            plate = self.slots[slot_id].get("vehicle_plate") or f"TRK-{self.slots[slot_id].get('track_id') or 'VEH'}"
            entry_ts = self.slots[slot_id].get("entry_timestamp") or entry_ts

        if not slot_id and not found_session:
            return None

        exit_ts = time.time()
        exit_dt = datetime.now()
        billing = self.calculate_billing(entry_ts, exit_ts)

        if found_session:
            found_session["status"] = "COMPLETED"
            found_session["exit_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            found_session["exit_timestamp"] = exit_ts
            found_session["duration_minutes"] = billing["duration_minutes"]
            found_session["duration_formatted"] = billing["duration_formatted"]
            found_session["fee_inr"] = billing["fee_inr"]
            found_session["fee_formatted"] = billing["fee_formatted"]

        origin_floor = 1
        if slot_id and slot_id in self.slots:
            origin_floor = self.slots[slot_id].get("floor", 1)
            new_status = "AVAILABLE"

            self.slots[slot_id]["status"] = new_status
            self.slots[slot_id]["type"] = "GENERAL"
            self.slots[slot_id]["is_ev"] = False
            self.slots[slot_id]["vehicle_plate"] = None
            self.slots[slot_id]["track_id"] = None
            self.slots[slot_id]["entry_timestamp"] = None
            self.slots[slot_id]["entry_time"] = None

        self.total_revenue_inr += billing["fee_inr"]
        exit_route = self.router.find_shortest_path(slot_id or "ENTRANCE", "EXIT")
        if exit_route:
            exit_route["origin_floor"] = origin_floor

        # Persist exit to SQLite DB
        db = SessionLocal()
        try:
            if found_session:
                db_sess = db.query(ParkingSession).filter(ParkingSession.session_id == found_session["session_id"]).first()
                if db_sess:
                    db_sess.status = "COMPLETED"
                    db_sess.exit_time = exit_dt
                    db_sess.exit_timestamp = exit_ts
                    db_sess.duration_seconds = billing["duration_seconds"]
                    db_sess.duration_formatted = billing["duration_formatted"]
                    db_sess.fee_inr = float(billing["fee_inr"])

            if slot_id:
                db_slot = db.query(ParkingSlot).filter(ParkingSlot.id == slot_id).first()
                if db_slot:
                    db_slot.status = "FREE"
                    db_slot.slot_type = "GENERAL"
                    db_slot.is_ev = False
                    db_slot.current_vehicle_plate = None
                    db_slot.current_track_id = None
                    db_slot.occupied_since = None

            db.commit()
        except Exception as e:
            print(f"[StateEngine] Error saving exit to DB: {e}")
            db.rollback()
        finally:
            db.close()

        self.log_event("EXIT", f"Vehicle {plate} vacated Bay {slot_id or 'RAMP'} (Floor {origin_floor}). Stay: {billing['duration_formatted']} • Charged: {billing['fee_formatted']} (₹20/30m)", {
            "plate": plate,
            "slot": slot_id,
            "floor": origin_floor,
            "duration": billing["duration_formatted"],
            "fee": billing["fee_formatted"]
        })

        return {
            "status": "COMPLETED",
            "plate_number": plate,
            "slot_id": slot_id,
            "floor": origin_floor,
            "billing": billing,
            "exit_route": exit_route
        }

    def get_db_slots_data(self):
        """
        Directly queries the parking_slots table from SQLite and returns list of slot dicts.
        """
        db = SessionLocal()
        try:
            slots = db.query(ParkingSlot).all()
            return [{
                "id": s.id,
                "slot_number": s.slot_number,
                "slot_type": s.slot_type,
                "status": s.status,
                "current_vehicle_plate": s.current_vehicle_plate,
                "current_track_id": s.current_track_id,
                "is_ev": s.is_ev,
                "distance_score": s.distance_score,
                "x": s.x,
                "y": s.y,
                "width": s.width,
                "height": s.height,
                "occupied_since": s.occupied_since.strftime("%Y-%m-%d %H:%M:%S") if s.occupied_since else None,
                "updated_at": s.updated_at.strftime("%Y-%m-%d %H:%M:%S") if s.updated_at else None
            } for s in slots]
        finally:
            db.close()

    def get_db_sessions_data(self, limit=100):
        """
        Directly queries the parking_sessions table from SQLite and returns vehicle session records.
        """
        db = SessionLocal()
        try:
            sessions = db.query(ParkingSession).order_by(ParkingSession.id.desc()).limit(limit).all()
            return [{
                "id": s.id,
                "session_id": s.session_id,
                "vehicle_plate": s.vehicle_plate,
                "vehicle_type": s.vehicle_type,
                "is_ev": s.is_ev,
                "assigned_slot": s.assigned_slot,
                "track_id": s.track_id,
                "camera_id": s.camera_id,
                "entry_time": s.entry_time.strftime("%Y-%m-%d %H:%M:%S") if s.entry_time else None,
                "entry_timestamp": s.entry_timestamp,
                "exit_time": s.exit_time.strftime("%Y-%m-%d %H:%M:%S") if s.exit_time else None,
                "exit_timestamp": s.exit_timestamp,
                "duration_seconds": s.duration_seconds,
                "duration_formatted": s.duration_formatted,
                "fee_inr": s.fee_inr,
                "status": s.status,
                "ocr_confidence": round(float(getattr(s, "ocr_confidence", 1.0) or 1.0) * 100, 1),
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S") if s.created_at else None
            } for s in sessions]
        finally:
            db.close()

    def get_summary_state(self):
        """
        Returns full authoritative Digital Twin summary state for frontend real-time synchronization.
        Includes latest_detection: the single most recently recorded session (any status),
        so the HUD always reflects the newest CV detection without hardcoded fallbacks.
        """
        total = len(self.slots)
        occupied = sum(1 for s in self.slots.values() if s["status"] == "OCCUPIED")
        allocated = sum(1 for s in self.slots.values() if s["status"] == "ALLOCATED")
        available = sum(1 for s in self.slots.values() if s["status"] in ["AVAILABLE", "FREE"])
        reserved = sum(1 for s in self.slots.values() if s["status"] == "RESERVED")
        restricted = sum(1 for s in self.slots.values() if s["status"] == "RESTRICTED")

        rate = round(((occupied + allocated) / max(total, 1)) * 100, 1)

        f1_slots = {k: v for k, v in self.slots.items() if v.get("floor") == 1}
        f2_slots = {k: v for k, v in self.slots.items() if v.get("floor") == 2}

        # Most recently recorded session regardless of status (sessions are prepended, so index 0 is latest)
        latest_detection = self.sessions[0] if self.sessions else None

        # Real-time revenue: Completed revenue today + active vehicles live accrued tariffs
        now_ts = time.time()
        active_revenue = 0
        for s in self.sessions:
            if s.get("status") in ["ACTIVE", "ENTERING", "PARKED"] and s.get("status") != "BYPASS":
                entry_ts = s.get("entry_timestamp") or now_ts
                billing = self.calculate_billing(entry_ts, now_ts)
                active_revenue += int(billing.get("fee_inr", self.rate_per_30_mins))

        live_total_revenue = int(self.total_revenue_inr + active_revenue)

        return {
            "facility_name": "PARKIQ MULTI-LEVEL PARKING (F1: 6 BAYS + F2: 28 BAYS)",
            "kpis": {
                "total_capacity": total,
                "available": available,
                "occupied": occupied,
                "allocated": allocated,
                "reserved": reserved,
                "restricted": restricted,
                "occupancy_rate": rate,
                "f1_capacity": len(f1_slots),
                "f1_available": sum(1 for s in f1_slots.values() if s["status"] in ["AVAILABLE", "FREE"]),
                "f1_occupied": sum(1 for s in f1_slots.values() if s["status"] == "OCCUPIED"),
                "f2_capacity": len(f2_slots),
                "f2_available": sum(1 for s in f2_slots.values() if s["status"] in ["AVAILABLE", "FREE"]),
                "f2_occupied": sum(1 for s in f2_slots.values() if s["status"] == "OCCUPIED"),
                "total_revenue_inr": live_total_revenue,
                "completed_revenue_inr": int(self.total_revenue_inr),
                "active_revenue_inr": active_revenue,
                "total_vehicles_today": self.total_vehicles_today,
                "rate_per_30m": self.rate_per_30_mins
            },
            "slots": self.slots,
            "active_sessions": [s for s in self.sessions if s["status"] in ["ACTIVE", "ENTERING", "PARKED", "BYPASS"]],
            "completed_sessions": [s for s in self.sessions if s["status"] == "COMPLETED"][:15],
            "activity_feed": self.activity_feed[:25],
            "latest_detection": latest_detection
        }

    def reset_facility(self):
        """
        Resets all slots in memory and SQLite DB to FREE, clears active sessions,
        and returns the fresh digital twin state.
        """
        db = SessionLocal()
        try:
            db_slots = db.query(ParkingSlot).all()
            for s in db_slots:
                s.status = "FREE"
                s.current_vehicle_plate = None
                s.current_track_id = None
                s.occupied_since = None
            
            active_sessions = db.query(ParkingSession).filter(
                ParkingSession.status.in_(["ENTERING", "PARKED", "ACTIVE", "BYPASS"])
            ).all()
            for sess in active_sessions:
                sess.status = "COMPLETED"
            
            db.commit()

            # Re-sync today's completed metrics from database
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_completed_rev = db.query(func.sum(ParkingSession.fee_inr)).filter(
                ParkingSession.status == "COMPLETED",
                ParkingSession.created_at >= today_start
            ).scalar()
            self.total_revenue_inr = int(float(today_completed_rev or 0))
            self.total_vehicles_today = db.query(ParkingSession).filter(ParkingSession.created_at >= today_start).count()

            # Reset in-memory slots
            for sid, sdata in self.slots.items():
                sdata["status"] = "AVAILABLE"
                sdata["vehicle_plate"] = None
                sdata["track_id"] = None
                sdata["entry_time"] = None
                sdata["entry_timestamp"] = None
                sdata["type"] = "GENERAL"

            # Clear active vehicles and reset in-memory session statuses
            self.active_vehicles.clear()
            for s in self.sessions:
                s["status"] = "COMPLETED"

            self.log_event("RESET", "Facility state reset: All 34 bays set to General Free.")
            return {"status": "SUCCESS", "message": "All 34 bays reset to General Free."}
        except Exception as e:
            db.rollback()
            return {"status": "ERROR", "message": str(e)}
        finally:
            db.close()

# Global Singleton State Engine
state_engine = ParkingStateEngine()
