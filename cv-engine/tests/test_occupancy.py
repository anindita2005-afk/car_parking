import unittest
import json
import tempfile
import os
from occupancy.slot_manager import SlotManager

class TestSlotManager(unittest.TestCase):
    def setUp(self):
        # Create a temporary config file
        self.config_data = {
            "camera_id": "CAM_TEST",
            "slots": [
                {
                    "id": "slot_1",
                    "polygon": [[0, 0], [100, 0], [100, 100], [0, 100]]
                },
                {
                    "id": "slot_2",
                    "polygon": [[200, 0], [300, 0], [300, 100], [200, 100]]
                }
            ]
        }
        self.fd, self.path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(self.fd, 'w') as f:
            json.dump(self.config_data, f)
            
    def tearDown(self):
        os.remove(self.path)
        
    def test_occupancy(self):
        manager = SlotManager(self.path)
        
        # Vehicle perfectly inside slot 1
        detections = [
            {"track_id": 1, "box": [10, 10, 90, 90], "class_id": 2, "confidence": 0.9}
        ]
        
        occupancy = manager.get_occupancy(detections)
        self.assertEqual(occupancy["slot_1"]["status"], "occupied")
        self.assertEqual(occupancy["slot_1"]["vehicle_id"], 1)
        self.assertEqual(occupancy["slot_2"]["status"], "empty")
        
        # Vehicle partially inside slot 2 (should be occupied depending on threshold)
        # Bounding box is 250,50 to 350,150. Area = 100x100 = 10000.
        # Intersection with slot_2 (200,0 to 300,100) is 250,50 to 300,100.
        # Intersection width = 50, height = 50. Area = 2500.
        # IoU = 2500 / (10000 + 10000 - 2500) = 2500 / 17500 = 0.14
        # Since threshold is 0.4, it should be empty.
        detections = [
            {"track_id": 2, "box": [250, 50, 350, 150], "class_id": 2, "confidence": 0.9}
        ]
        
        occupancy = manager.get_occupancy(detections)
        self.assertEqual(occupancy["slot_1"]["status"], "empty")
        self.assertEqual(occupancy["slot_2"]["status"], "empty")
        
if __name__ == '__main__':
    unittest.main()
