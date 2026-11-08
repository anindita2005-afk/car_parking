import os
from ultralytics import YOLO

class VehicleDetector:
    """
    Vehicle Detection and Multi-Object Tracking Engine based on YOLOv8.
    Tracks cars, motorcycles, buses, and trucks, providing persistent track IDs.
    """
    def __init__(self, model_name="yolov8n.pt"):
        # Load YOLOv8 Nano model for fast real-time inference on CPU/GPU
        self.model = YOLO(model_name)
        # COCO vehicle class IDs: 2: car, 3: motorcycle, 5: bus, 7: truck
        self.vehicle_classes = [2, 3, 5, 7]

    def detect_and_track(self, frame, conf_threshold=0.35):
        """
        Detects and tracks vehicles across frames.
        Returns a list of detections:
        [{"track_id": int, "box": [x1, y1, x2, y2], "class_id": int, "confidence": float}, ...]
        """
        detections = []
        if frame is None or frame.size == 0:
            return detections

        try:
            # Run YOLOv8 tracker with ByteTrack / BoT-SORT
            results = self.model.track(
                frame,
                classes=self.vehicle_classes,
                persist=True,
                conf=conf_threshold,
                verbose=False
            )

            for result in results:
                boxes = result.boxes
                if boxes is not None and len(boxes) > 0:
                    track_ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [-1] * len(boxes)
                    
                    for i, box in enumerate(boxes):
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        conf = float(box.conf[0].item())
                        cls_id = int(box.cls[0].item())
                        t_id = track_ids[i] if i < len(track_ids) else -1

                        detections.append({
                            "track_id": t_id,
                            "box": [int(x1), int(y1), int(x2), int(y2)],
                            "class_id": cls_id,
                            "confidence": round(conf, 3)
                        })
        except Exception as e:
            # Fallback to standard detect if tracker encounters initialization hiccup on first frame
            try:
                results = self.model(frame, classes=self.vehicle_classes, conf=conf_threshold, verbose=False)
                for result in results:
                    for i, box in enumerate(result.boxes):
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        conf = float(box.conf[0].item())
                        cls_id = int(box.cls[0].item())
                        detections.append({
                            "track_id": i + 1,
                            "box": [int(x1), int(y1), int(x2), int(y2)],
                            "class_id": cls_id,
                            "confidence": round(conf, 3)
                        })
            except Exception as inner_e:
                print(f"[VehicleDetector] Inference error: {inner_e}")

        return detections

