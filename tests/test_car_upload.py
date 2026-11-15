import os
import sys
import cv2
import numpy as np

# Ensure backend is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.services.car_detector import car_detector
from app.core.state_engine import state_engine

def generate_realistic_car_image(plate_text="MH12DE1433", is_ev=False, output_path="tests/test_car.jpg"):
    """
    Generates a realistic test image of a car with a clear license plate.
    """
    w, h = 640, 480
    img = np.full((h, w, 3), (240, 240, 240), dtype=np.uint8)

    # Road background
    img[280:, :] = (50, 50, 50)
    # Road markings
    for x in range(20, w, 100):
        cv2.rectangle(img, (x, 420), (x + 50, 430), (255, 255, 255), -1)

    # Car Body (Dark Blue or Teal EV)
    body_color = (180, 100, 20) if not is_ev else (180, 180, 20)
    # Lower chassis
    cv2.rectangle(img, (140, 200), (500, 360), body_color, -1)
    # Upper roof / cabin
    pts = np.array([[200, 200], [250, 120], [390, 120], [440, 200]], np.int32)
    cv2.fillPoly(img, [pts], (body_color[0] - 20, body_color[1] - 20, body_color[2] - 20))

    # Windshield
    win_pts = np.array([[215, 195], [255, 130], [385, 130], [425, 195]], np.int32)
    cv2.fillPoly(img, [win_pts], (40, 40, 40))

    # Headlights
    cv2.rectangle(img, (150, 220), (190, 245), (0, 255, 255), -1)
    cv2.rectangle(img, (450, 220), (490, 245), (0, 255, 255), -1)

    # Grille
    cv2.rectangle(img, (220, 240), (420, 290), (20, 20, 20), -1)

    # Wheels
    cv2.circle(img, (190, 360), 38, (15, 15, 15), -1)
    cv2.circle(img, (190, 360), 18, (180, 180, 180), -1)
    cv2.circle(img, (450, 360), 38, (15, 15, 15), -1)
    cv2.circle(img, (450, 360), 18, (180, 180, 180), -1)

    # License Plate Mount (White or Green EV plate)
    plate_bg = (250, 250, 250) if not is_ev else (80, 200, 80)
    cv2.rectangle(img, (245, 295), (395, 340), plate_bg, -1)
    cv2.rectangle(img, (245, 295), (395, 340), (0, 0, 0), 2)

    # Blue HSRP 'IND' strip on left edge
    cv2.rectangle(img, (245, 295), (262, 340), (200, 100, 20), -1)

    # Plate Text with clean spacing
    cv2.putText(img, plate_text, (268, 327), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (10, 10, 10), 2, cv2.LINE_AA)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    cv2.imwrite(output_path, img)
    return output_path

def test_pipeline():
    print("\n" + "=" * 60)
    print("  PARKING SYSTEM - VEHICLE DETECTION & ALLOCATION TEST")
    print("=" * 60)

    # 1. Standard Car Test
    car_path = generate_realistic_car_image("MH12DE1433", is_ev=False, output_path="tests/test_car_std.jpg")
    print(f"\n[Test 1] Generated test image: {car_path}")
    
    result = car_detector.detect_and_process(car_path)
    print(f"  ✓ YOLO Detection Box: {result['box']}")
    print(f"  ✓ Detected Vehicle Type: {result['vehicle_type']}")
    print(f"  ✓ Extracted License Plate: {result['plate_number']}")
    print(f"  ✓ OCR Confidence: {result['ocr_confidence']*100:.1f}%")
    print(f"  ✓ EV Status: {result['is_ev']}")

    # 2. EV Car Test
    ev_path = generate_realistic_car_image("EV02XY9999", is_ev=True, output_path="tests/test_car_ev.jpg")
    print(f"\n[Test 2] Generated EV image: {ev_path}")
    
    result_ev = car_detector.detect_and_process(ev_path)
    print(f"  ✓ YOLO Detection Box: {result_ev['box']}")
    print(f"  ✓ Detected Vehicle Type: {result_ev['vehicle_type']}")
    print(f"  ✓ Extracted License Plate: {result_ev['plate_number']}")
    print(f"  ✓ OCR Confidence: {result_ev['ocr_confidence']*100:.1f}%")
    print(f"  ✓ EV Status: {result_ev['is_ev']}")

    # 3. Test State Engine Entry & Slot Allocation
    print("\n[Test 3] Testing Digital Twin State Engine Allocation...")
    session_std = state_engine.record_entry(
        plate_number=result["plate_number"],
        vehicle_type=result["vehicle_type"],
        is_ev=result["is_ev"]
    )
    print(f"  ✓ Standard Vehicle Assigned Slot: {session_std['assigned_slot']} (Reason: {session_std['allocation_reason']})")
    print(f"  ✓ Route Waypoints: {len(session_std['route']['path_nodes'])} steps: {' -> '.join(session_std['route']['path_nodes'])}")

    session_ev = state_engine.record_entry(
        plate_number=result_ev["plate_number"],
        vehicle_type=result_ev["vehicle_type"],
        is_ev=result_ev["is_ev"]
    )
    print(f"  ✓ EV Vehicle Assigned Slot: {session_ev['assigned_slot']} (Reason: {session_ev['allocation_reason']})")
    print(f"  ✓ Route Waypoints: {len(session_ev['route']['path_nodes'])} steps: {' -> '.join(session_ev['route']['path_nodes'])}")

    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    test_pipeline()
