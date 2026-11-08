import json
from shapely.geometry import Polygon, Point, box

class SlotManager:
    """
    Polygon-based Parking Slot Occupancy Engine.
    Uses computational geometry (IoU and Point-in-Polygon containment) to evaluate
    which configured parking bay is occupied by detected vehicles.
    """
    def __init__(self, config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
            
        self.camera_id = config.get("camera_id", "CAM_01")
        self.slots = {}
        for slot in config.get("slots", []):
            poly = Polygon(slot["polygon"])
            self.slots[slot["id"]] = {
                "polygon": poly,
                "status": "empty",
                "vehicle_id": None
            }
            
    def get_occupancy(self, vehicle_detections, iou_threshold=0.25):
        """
        Takes vehicle detections and calculates occupancy per configured slot polygon.
        Returns: dict of slot_id -> {"status": "occupied"|"empty", "vehicle_id": int|None}
        """
        # Reset all slots to empty
        for slot_id in self.slots:
            self.slots[slot_id]["status"] = "empty"
            self.slots[slot_id]["vehicle_id"] = None
            
        occupancy_map = {}
            
        for det in vehicle_detections:
            x1, y1, x2, y2 = det['box']
            track_id = det.get('track_id')
            
            # Create a Shapely geometry for the vehicle
            vehicle_poly = box(x1, y1, x2, y2)
            vehicle_center = Point((x1 + x2) / 2.0, (y1 + y2) / 2.0)
            
            for slot_id, slot_data in self.slots.items():
                slot_poly = slot_data["polygon"]
                
                # Check 1: Intersection over Union (IoU)
                intersection = vehicle_poly.intersection(slot_poly).area
                union = vehicle_poly.area + slot_poly.area - intersection
                iou = (intersection / union) if union > 0 else 0
                
                # Check 2: Vehicle Centroid or Overlap containment
                centroid_inside = slot_poly.contains(vehicle_center)
                overlap_ratio = (intersection / slot_poly.area) if slot_poly.area > 0 else 0
                
                if iou >= iou_threshold or centroid_inside or overlap_ratio >= 0.35:
                    self.slots[slot_id]["status"] = "occupied"
                    self.slots[slot_id]["vehicle_id"] = track_id
                        
        for slot_id, slot_data in self.slots.items():
            occupancy_map[slot_id] = {
                "status": slot_data["status"],
                "vehicle_id": slot_data["vehicle_id"]
            }
            
        return occupancy_map

