import unittest
import numpy as np

class MockDetector:
    def detect(self, frame):
        # Return a dummy detection for a car
        return [{"box": [10, 10, 100, 100], "class_id": 2, "confidence": 0.9}]

class MockReader:
    def read_plate(self, crop):
        return "TESTPLT", 0.95

class TestPipeline(unittest.TestCase):
    def test_mock_pipeline(self):
        detector = MockDetector()
        reader = MockReader()
        
        # Create a dummy image
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        
        detections = detector.detect(frame)
        self.assertEqual(len(detections), 1)
        
        plate, conf = reader.read_plate(frame)
        self.assertEqual(plate, "TESTPLT")

if __name__ == '__main__':
    unittest.main()
