import cv2
import numpy as np
import os
import json

def create_synthetic_parking_video(output_path="parking_test.mp4", duration_sec=15, fps=30):
    """
    Generates a realistic synthetic parking video with:
    1. Realistic parking bays matching slots_config.json
    2. Vehicles entering via the gate
    3. Clearly readable license plates with realistic fonts and contrasts
    4. Vehicle motion from entrance to assigned slots
    5. Vehicle stopping and occupying the slot
    """
    width, height = 960, 640
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    total_frames = duration_sec * fps

    # Slot definitions matching slots_config.json
    slots = [
        {"id": "S01", "type": "STANDARD", "rect": (140, 40, 80, 120), "is_ev": False},
        {"id": "S02", "type": "STANDARD", "rect": (280, 40, 80, 120), "is_ev": False},
        {"id": "S03", "type": "LARGE", "rect": (420, 40, 90, 130), "is_ev": False},
        {"id": "S04", "type": "EV", "rect": (560, 40, 80, 120), "is_ev": True},
        {"id": "S05", "type": "EV", "rect": (700, 40, 80, 120), "is_ev": True},
        {"id": "S06", "type": "STANDARD", "rect": (140, 480, 80, 120), "is_ev": False},
        {"id": "S07", "type": "STANDARD", "rect": (280, 480, 80, 120), "is_ev": False},
        {"id": "S08", "type": "LARGE", "rect": (420, 480, 90, 130), "is_ev": False},
        {"id": "S09", "type": "RESERVED", "rect": (560, 480, 80, 120), "is_ev": False},
        {"id": "S10", "type": "RESTRICTED", "rect": (700, 480, 80, 120), "is_ev": False},
    ]

    # Pre-parked car in S01 to show initial occupancy
    pre_parked = [
        {"slot_id": "S01", "plate": "DL01AB1122", "color": (160, 80, 40)}
    ]

    # Test vehicles entering sequentially
    vehicles = [
        {
            "id": 101,
            "plate": "WB12AB1234",
            "type": "car",
            "is_ev": False,
            "color": (220, 140, 30), # Blue-ish BGR
            "start_frame": 10,
            "end_frame": 220,
            "target_slot": "S02",
            "waypoints": [
                (40, 320),      # Entrance
                (180, 320),     # Aisle 1
                (280, 320),     # Below S02
                (320, 100)      # Inside S02
            ]
        },
        {
            "id": 102,
            "plate": "EV99KA2024",
            "type": "car",
            "is_ev": True,
            "color": (40, 180, 60),  # Green-ish BGR
            "start_frame": 180,
            "end_frame": 420,
            "target_slot": "S04",
            "waypoints": [
                (40, 320),      # Entrance
                (300, 320),     # Aisle
                (560, 320),     # Below S04
                (600, 100)      # Inside S04
            ]
        }
    ]

    def draw_car(frame, x, y, width, height, angle_deg, color, plate_text):
        # Draw realistic vehicle with wheels, headlights, windshield, roof, and license plate
        cx, cy = int(x), int(y)
        w, h = int(width), int(height)
        
        # 1. Wheels (4 black rounded tires at corners)
        tire_w, tire_h = 10, 24
        cv2.rectangle(frame, (cx - w//2 - 4, cy - h//2 + 12), (cx - w//2 + 4, cy - h//2 + 12 + tire_h), (20, 20, 20), -1)
        cv2.rectangle(frame, (cx + w//2 - 4, cy - h//2 + 12), (cx + w//2 + 4, cy - h//2 + 12 + tire_h), (20, 20, 20), -1)
        cv2.rectangle(frame, (cx - w//2 - 4, cy + h//2 - 32), (cx - w//2 + 4, cy + h//2 - 32 + tire_h), (20, 20, 20), -1)
        cv2.rectangle(frame, (cx + w//2 - 4, cy + h//2 - 32), (cx + w//2 + 4, cy + h//2 - 32 + tire_h), (20, 20, 20), -1)

        # 2. Main Car Body with metallic gradient / border
        cv2.rectangle(frame, (cx - w//2, cy - h//2), (cx + w//2, cy + h//2), color, -1)
        cv2.rectangle(frame, (cx - w//2, cy - h//2), (cx + w//2, cy + h//2), (240, 240, 240), 2)

        # 3. Headlights & Taillights
        cv2.rectangle(frame, (cx - w//2 + 4, cy - h//2 + 2), (cx - w//2 + 16, cy - h//2 + 8), (180, 255, 255), -1)
        cv2.rectangle(frame, (cx + w//2 - 16, cy - h//2 + 2), (cx + w//2 - 4, cy - h//2 + 8), (180, 255, 255), -1)
        
        # 4. Front & Rear Windshields
        cv2.rectangle(frame, (cx - w//2 + 8, cy - h//2 + 18), (cx + w//2 - 8, cy - h//2 + 36), (45, 55, 75), -1)
        cv2.rectangle(frame, (cx - w//2 + 8, cy + h//2 - 38), (cx + w//2 - 8, cy + h//2 - 20), (45, 55, 75), -1)
        
        # 5. Roof cabin
        cv2.rectangle(frame, (cx - w//2 + 6, cy - h//2 + 36), (cx + w//2 - 6, cy + h//2 - 38), 
                      (int(color[0]*0.85), int(color[1]*0.85), int(color[2]*0.85)), -1)

        # 6. High-Contrast License Plate Badge (Indian White & Yellow background with black bold text)
        is_ev = "EV" in plate_text or "E" in plate_text[:2]
        plate_bg = (240, 255, 240) if is_ev else (255, 255, 255)
        plate_w, plate_h = int(w * 0.82), 22
        px1 = cx - plate_w // 2
        py1 = cy + h // 2 - 10
        cv2.rectangle(frame, (px1, py1), (px1 + plate_w, py1 + plate_h), plate_bg, -1)
        cv2.rectangle(frame, (px1, py1), (px1 + plate_w, py1 + plate_h), (0, 0, 0), 2)
        
        # Bold plate text
        cv2.putText(frame, plate_text, (px1 + 4, py1 + 16),
                    cv2.FONT_HERSHEY_DUPLEX, 0.48, (0, 0, 0), 1, cv2.LINE_AA)


    for f_idx in range(total_frames):
        # 1. Draw Parking Facility Layout
        frame = np.full((height, width, 3), (18, 24, 34), dtype=np.uint8) # Dark modern asphalt

        # Main driving lane
        cv2.rectangle(frame, (30, 260), (930, 380), (28, 38, 54), -1)
        
        # Lane divider dashed line
        for lx in range(40, 920, 40):
            cv2.line(frame, (lx, 320), (lx + 20, 320), (200, 200, 200), 2)

        # Entrance & Exit Text
        cv2.putText(frame, "GATE ENTRANCE [CAM_01]", (40, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 180, 255), 2)
        cv2.putText(frame, "GATE EXIT [CAM_02]", (740, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 230, 140), 2)

        # Draw Parking Slots
        for slot in slots:
            sx, sy, sw, sh = slot["rect"]
            slot_type = slot["type"]
            is_ev = slot["is_ev"]

            # Border color based on type
            border_color = (80, 80, 80)
            if is_ev:
                border_color = (220, 180, 20) # Cyan/EV
            elif slot_type == "RESERVED":
                border_color = (50, 150, 250)
            elif slot_type == "RESTRICTED":
                border_color = (50, 50, 200)

            # Slot box
            cv2.rectangle(frame, (sx, sy), (sx + sw, sy + sh), (32, 44, 62), -1)
            cv2.rectangle(frame, (sx, sy), (sx + sw, sy + sh), border_color, 2)
            
            # Slot label
            cv2.putText(frame, slot["id"], (sx + 8, sy + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)
            cv2.putText(frame, slot_type[:3], (sx + 8, sy + 38), cv2.FONT_HERSHEY_SIMPLEX, 0.35, border_color, 1)

        # Draw pre-parked cars
        draw_car(frame, 180, 100, 60, 100, 0, (140, 60, 30), "DL01AB1122")

        # Animate moving vehicles
        for v in vehicles:
            if v["start_frame"] <= f_idx <= v["end_frame"]:
                progress = (f_idx - v["start_frame"]) / (v["end_frame"] - v["start_frame"])
                
                # Interpolate along waypoints
                wpts = v["waypoints"]
                num_segs = len(wpts) - 1
                seg_idx = min(int(progress * num_segs), num_segs - 1)
                seg_prog = (progress * num_segs) - seg_idx
                
                p1 = wpts[seg_idx]
                p2 = wpts[seg_idx + 1]
                
                curr_x = p1[0] + (p2[0] - p1[0]) * seg_prog
                curr_y = p1[1] + (p2[1] - p1[1]) * seg_prog
                
                # Draw active car with plate
                draw_car(frame, curr_x, curr_y, 64, 105, 0, v["color"], v["plate"])
            elif f_idx > v["end_frame"]:
                # Keep car parked in target slot
                last_pt = v["waypoints"][-1]
                draw_car(frame, last_pt[0], last_pt[1], 64, 105, 0, v["color"], v["plate"])

        out.write(frame)

    out.release()
    print(f"[Synthetic Video Generator] Successfully created {output_path} ({total_frames} frames, {fps} FPS)")

if __name__ == "__main__":
    out_file = os.path.join(os.path.dirname(__file__), "parking_test.mp4")
    create_synthetic_parking_video(out_file, duration_sec=12, fps=30)
