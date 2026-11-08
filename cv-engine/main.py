import cv2
import requests
import time
import os
import sys
import json
from detection.detector import VehicleDetector
from anpr.ocr import PlateReader
from tracking.state import TrackingState
from occupancy.slot_manager import SlotManager

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000/api")

def process_video_feed(video_source, detector, reader, state, slot_manager, camera_id="CAM_01", display=True):
    """
    Ingests video file or webcam stream, runs YOLOv8 tracking + ANPR OCR + polygon slot occupancy,
    renders on-screen visual analytics HUD, and syncs real-time events to the Backend API.
    """
    # Parse source
    if isinstance(video_source, str) and video_source.isdigit():
        video_source = int(video_source)

    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"[CV Engine] Error: Could not open video source: {video_source}")
        return

    print("\n" + "=" * 65)
    print(f"  [PARKIQ CV ENGINE] ACTIVE - Camera: {camera_id}")
    print(f"  Video Source: {video_source}")
    print(f"  Backend API: {BACKEND_API_URL}")
    print(f"  Controls: Press 'q' in the video window to stop.")
    print("=" * 65 + "\n")

    frame_count = 0
    process_interval = 1  # Process every frame for high tracking continuity

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            # If video reached end, loop for live continuous testing if it's a test file
            if isinstance(video_source, str) and os.path.exists(video_source):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            break

        frame_count += 1
        h, w = frame.shape[:2]

        # 1. YOLOv8 Vehicle Detection & Multi-Object Tracking
        detections = detector.detect_and_track(frame)

        # 2. Polygon-Zone Slot Occupancy Calculation
        occupancy_map = slot_manager.get_occupancy(detections)

        # Transmit occupancy updates to backend
        try:
            requests.post(
                f"{BACKEND_API_URL}/occupancy",
                json={"camera_id": camera_id, "slots": occupancy_map},
                timeout=0.3
            )
        except Exception:
            pass  # Non-blocking if backend is starting

        # 3. Vehicle Plate Recognition & Registration
        for det in detections:
            track_id = det['track_id']
            if track_id == -1:
                continue

            x1, y1, x2, y2 = det['box']
            cls_id = det['class_id']
            conf = det['confidence']

            class_map = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
            v_type = class_map.get(cls_id, "car")

            identity = state.get_identity(track_id)

            # Try to read plate if not yet confidently recognized
            if identity is None or identity['confidence'] < 0.60:
                # Lower half / center of bounding box holds the license plate
                box_h = y2 - y1
                y1_crop = max(0, min(int(y1 + box_h * 0.35), h - 1))
                y2_crop = max(0, min(y2, h - 1))
                x1_crop = max(0, min(x1, w - 1))
                x2_crop = max(0, min(x2, w - 1))

                vehicle_crop = frame[y1_crop:y2_crop, x1_crop:x2_crop]

                if vehicle_crop.size > 0:
                    plate_text, ocr_conf = reader.read_plate(vehicle_crop)
                    if plate_text and len(plate_text) >= 4:
                        state.set_identity(track_id, plate_text, ocr_conf)

            # Check if recognized and needs to register entry session with Backend
            identity = state.get_identity(track_id)
            if identity and not state.is_reported(track_id) and identity['confidence'] >= 0.40:
                plate_str = identity['plate_text']
                ocr_score = identity['confidence']

                payload = {
                    "plate_number": plate_str,
                    "vehicle_type": "ev" if str(plate_str).strip().upper().startswith("EV") else v_type,
                    "is_ev": str(plate_str).strip().upper().startswith("EV"),
                    "track_id": track_id,
                    "camera_id": camera_id,
                    "confidence": float(conf),
                    "ocr_confidence": float(ocr_score)
                }

                try:
                    res = requests.post(f"{BACKEND_API_URL}/entry", json=payload, timeout=1.0)
                    if res.status_code == 200:
                        data = res.json()
                        assigned_slot = data.get("assigned_slot")
                        print(f"🚗 [ENTRY DETECTED] Track #{track_id} | Plate: {plate_str} (OCR: {ocr_score*100:.1f}%) -> Assigned Slot: {assigned_slot}")
                        state.mark_reported(track_id)
                except Exception as e:
                    print(f"⚠️ [Backend Connection] {e}")

        # 4. Render Visual Analytics HUD on Frame
        if display:
            # Draw slot polygons with live occupancy status
            for slot_id, slot_data in slot_manager.slots.items():
                poly_pts = list(slot_data["polygon"].exterior.coords)
                pts_np = [(int(p[0]), int(p[1])) for p in poly_pts]
                is_occ = slot_data["status"] == "occupied"
                color = (40, 40, 220) if is_occ else (40, 200, 80) # Red if occupied, green if empty
                
                # Draw outline
                for i in range(len(pts_np) - 1):
                    cv2.line(frame, pts_np[i], pts_np[i + 1], color, 2)
                
                # Slot label
                cv2.putText(frame, f"{slot_id}: {'OCCUPIED' if is_occ else 'AVAIL'}",
                            (pts_np[0][0] + 5, pts_np[0][1] + 18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

            # Draw vehicle bounding boxes & OCR tags
            for det in detections:
                bx1, by1, bx2, by2 = det['box']
                t_id = det['track_id']
                ident = state.get_identity(t_id)
                plate_text = ident['plate_text'] if ident else f"TRACK #{t_id}"
                ocr_str = f"({ident['confidence']*100:.0f}%)" if ident else ""
                
                # Vehicle Bounding Box
                cv2.rectangle(frame, (bx1, by1), (bx2, by2), (255, 180, 40), 2)
                
                # Label tag
                tag_label = f"{plate_text} {ocr_str}"
                (tw, th), _ = cv2.getTextSize(tag_label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                cv2.rectangle(frame, (bx1, by1 - 24), (bx1 + tw + 12, by1), (255, 180, 40), -1)
                cv2.putText(frame, tag_label, (bx1 + 6, by1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2, cv2.LINE_AA)

            # Top Telemetry Header
            cv2.rectangle(frame, (0, 0), (w, 36), (15, 20, 30), -1)
            cv2.putText(frame, f"PARKIQ CV ENGINE | CAM: {camera_id} | VEHICLES TRACKED: {len(detections)}",
                        (15, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

            cv2.imshow("PARKIQ - Intelligent Parking CV Engine", frame)
            if cv2.waitKey(15) & 0xFF == ord('q'):
                break

    cap.release()
    cv2.destroyAllWindows()
    print("[CV Engine] Stream processing stopped.")

def main():
    print("Initializing CV Engine Components...")
    detector = VehicleDetector()
    reader = PlateReader()
    state = TrackingState()

    config_path = os.path.join(os.path.dirname(__file__), "slots_config.json")
    slot_manager = SlotManager(config_path)

    if len(sys.argv) > 1:
        source = sys.argv[1]
    else:
        # Default to generated synthetic test video if it exists
        test_video = os.path.join(os.path.dirname(__file__), "parking_test.mp4")
        if os.path.exists(test_video):
            source = test_video
            print(f"Using default test video: {source}")
        else:
            print("Usage: python main.py <path_to_video.mp4> or python main.py 0 (webcam)")
            source = 0

    process_video_feed(source, detector, reader, state, slot_manager)

if __name__ == "__main__":
    main()

