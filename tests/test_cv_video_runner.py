import os
import sys
import cv2

# Set paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cv-engine")))

from detection.detector import VehicleDetector
from anpr.ocr import PlateReader
from tracking.state import TrackingState
from occupancy.slot_manager import SlotManager
import requests

def test_cv_engine_on_video():
    print("=== Testing CV Engine on Synthetic Parking Video ===")
    video_path = os.path.join(os.path.dirname(__file__), "..", "cv-engine", "parking_test.mp4")
    config_path = os.path.join(os.path.dirname(__file__), "..", "cv-engine", "slots_config.json")
    
    assert os.path.exists(video_path), f"Video not found at {video_path}"
    
    detector = VehicleDetector()
    reader = PlateReader()
    state = TrackingState()
    slot_manager = SlotManager(config_path)
    
    cap = cv2.VideoCapture(video_path)
    assert cap.isOpened(), "Failed to open test video"
    
    frame_idx = 0
    detections_found = 0
    plates_read = 0
    occupancy = {}
    
    while cap.isOpened() and frame_idx < 120:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        
        # 1. Detection & Tracking
        detections = detector.detect_and_track(frame)
        if detections:
            detections_found += 1
            
        # 2. Slot Occupancy
        occupancy = slot_manager.get_occupancy(detections)
        
        # 3. Plate OCR extraction
        h, w = frame.shape[:2]
        for det in detections:
            t_id = det["track_id"]
            if t_id == -1:
                continue
            x1, y1, x2, y2 = det["box"]
            box_h = y2 - y1
            y1_crop = max(0, min(int(y1 + box_h * 0.35), h - 1))
            y2_crop = max(0, min(y2, h - 1))
            x1_crop = max(0, min(x1, w - 1))
            x2_crop = max(0, min(x2, w - 1))
            
            crop = frame[y1_crop:y2_crop, x1_crop:x2_crop]
            if crop.size > 0:
                plate_text, conf = reader.read_plate(crop)
                if plate_text:
                    plates_read += 1
                    state.set_identity(t_id, plate_text, conf)
                    print(f"  Frame {frame_idx} | Track #{t_id} -> Plate: {plate_text} (Conf: {conf*100:.1f}%)")

    cap.release()
    print("\n--- Summary of CV Test ---")
    print(f"Frames processed: {frame_idx}")
    print(f"Frames with detections: {detections_found}")
    print(f"Identified tracks in state: {len(state.identities)}")
    for t_id, data in state.identities.items():
        print(f"  Track #{t_id}: Plate '{data['plate_text']}' with confidence {data['confidence']*100:.1f}%")
        
    print("Occupancy map at last frame:")
    for s_id, d in occupancy.items():
        if d["status"] == "occupied":
            print(f"  Slot {s_id}: OCCUPIED by vehicle #{d['vehicle_id']}")

    print("\n[SUCCESS]: CV Engine video test completed successfully.")

if __name__ == "__main__":
    test_cv_engine_on_video()
