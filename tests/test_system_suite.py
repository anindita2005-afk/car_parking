import unittest
import sys
import os

# Ensure backend and cv-engine paths are loaded
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cv-engine")))

from app.allocation.engine import SlotAllocator
from app.navigation.router import ParkingRouter
from app.core.state_engine import ParkingStateEngine
from anpr.ocr import PlateReader
from occupancy.slot_manager import SlotManager
from tracking.state import TrackingState

class TestIntelligentParkingSystem(unittest.TestCase):
    def setUp(self):
        self.allocator = SlotAllocator()
        self.router = ParkingRouter()
        self.state_engine = ParkingStateEngine()
        self.plate_reader = PlateReader()
        self.tracking_state = TrackingState()
        
        cv_config_path = os.path.join(os.path.dirname(__file__), "..", "cv-engine", "slots_config.json")
        self.slot_manager = SlotManager(cv_config_path)

    def test_general_allocation_proximity(self):
        """Verify vehicles receive optimal general slots based on proximity score"""
        res = self.allocator.allocate(occupancy_map={}, vehicle_type="car")
        self.assertIsNotNone(res)
        self.assertEqual(res["slot_type"], "GENERAL")
        self.assertIn("General", res["reason"])

    def test_unified_vehicle_allocation(self):
        """Verify all vehicles are treated as general vehicles without size categories"""
        res = self.allocator.allocate(occupancy_map={}, vehicle_type="truck")
        self.assertIsNotNone(res)
        self.assertEqual(res["slot_type"], "GENERAL")

    def test_pathfinding_a_star_route(self):
        """Verify A* route calculation returns coordinate waypoints from entrance to slot"""
        route = self.router.find_shortest_path(start="ENTRANCE", target="S02")
        self.assertIsNotNone(route)
        self.assertIn("ENTRANCE", route["path_nodes"])
        self.assertIn("S02", route["path_nodes"])
        self.assertTrue(len(route["coordinates"]) >= 2)
        self.assertGreater(route["distance_pixels"], 0)

    def test_polygon_slot_occupancy(self):
        """Verify CV polygon IoU and containment accurately detects slot occupancy"""
        # Vehicle bounding box directly inside S01 (x: 160-265, y: 130-192)
        simulated_detections = [
            {"track_id": 101, "box": [170, 135, 260, 185], "class_id": 2, "confidence": 0.95}
        ]
        occupancy = self.slot_manager.get_occupancy(simulated_detections)
        self.assertEqual(occupancy["S01"]["status"], "occupied")
        self.assertEqual(occupancy["S01"]["vehicle_id"], 101)
        self.assertEqual(occupancy["S02"]["status"], "empty")

    def test_plate_normalizer(self):
        """Verify ANPR plate text normalization strips invalid characters and standardizes format"""
        normalized = self.plate_reader.normalize_plate_text("  wb-12-ab-1234. ")
        self.assertEqual(normalized, "WB12AB1234")

    def test_tracking_state_persistence(self):
        """Verify vehicle tracking state aggregates OCR confidence votes"""
        self.tracking_state.set_identity(track_id=42, plate_text="WB12AB1234", confidence=0.75)
        ident1 = self.tracking_state.get_identity(42)
        self.assertIsNotNone(ident1)
        assert ident1 is not None
        self.assertEqual(ident1["plate_text"], "WB12AB1234")
        
        # Should update when higher confidence is found
        self.tracking_state.set_identity(track_id=42, plate_text="WB12AB1234", confidence=0.95)
        ident2 = self.tracking_state.get_identity(42)
        self.assertIsNotNone(ident2)
        assert ident2 is not None
        self.assertEqual(ident2["confidence"], 0.95)

    def test_state_engine_lifecycle(self):
        """Verify entry -> allocation -> occupancy -> exit lifecycle in central state engine"""
        # 1. Entry
        session = self.state_engine.record_entry(
            plate_number="WB12AB1234",
            vehicle_type="car",
            is_ev=False,
            track_id=17,
            ocr_conf=0.94
        )
        self.assertEqual(session["plate_number"], "WB12AB1234")
        self.assertIsNotNone(session["assigned_slot"])
        assigned_slot = session["assigned_slot"]

        # 2. Occupy Slot via CV
        self.state_engine.update_occupancy_from_cv({
            assigned_slot: {"status": "OCCUPIED", "vehicle_id": 17}
        })
        summary = self.state_engine.get_summary_state()
        self.assertEqual(summary["slots"][assigned_slot]["status"], "OCCUPIED")

        # 3. Exit
        exit_sess = self.state_engine.record_exit("WB12AB1234")
        self.assertIsNotNone(exit_sess)
        self.assertEqual(exit_sess["status"], "COMPLETED")

    def test_floor_specific_simulation_lifecycle(self):
        """Verify Floor 1 and Floor 2 distinct entry -> park -> exit simulation lifecycles"""
        # --- Floor 1 Lifecycle ---
        f1_entry = self.state_engine.record_entry(
            plate_number="DL01AA1111",
            vehicle_type="car",
            is_ev=False,
            preferred_floor=1
        )
        self.assertIsNotNone(f1_entry["assigned_slot"])
        self.assertTrue(f1_entry["assigned_slot"].startswith("F1-"))
        self.assertEqual(f1_entry["status"], "ENTERING")

        # Park Floor 1 vehicle
        f1_park = self.state_engine.record_park(floor=1)
        self.assertEqual(f1_park["status"], "SUCCESS")
        self.assertEqual(f1_park["floor"], 1)
        self.assertEqual(self.state_engine.slots[f1_entry["assigned_slot"]]["status"], "OCCUPIED")

        # Exit Floor 1 vehicle
        f1_exit = self.state_engine.record_exit(floor=1)
        self.assertIsNotNone(f1_exit)
        self.assertEqual(f1_exit["floor"], 1)
        self.assertEqual(f1_exit["plate_number"], "DL01AA1111")
        self.assertEqual(self.state_engine.slots[f1_entry["assigned_slot"]]["status"], "AVAILABLE")

        # --- Floor 2 Lifecycle ---
        f2_entry = self.state_engine.record_entry(
            plate_number="MH02BB2222",
            vehicle_type="car",
            is_ev=False,
            preferred_floor=2
        )
        self.assertIsNotNone(f2_entry["assigned_slot"])
        self.assertTrue(f2_entry["assigned_slot"].startswith("F2-"))
        self.assertEqual(f2_entry["status"], "ENTERING")

        # Park Floor 2 vehicle
        f2_park = self.state_engine.record_park(floor=2)
        self.assertEqual(f2_park["status"], "SUCCESS")
        self.assertEqual(f2_park["floor"], 2)
        self.assertEqual(self.state_engine.slots[f2_entry["assigned_slot"]]["status"], "OCCUPIED")

        # Exit Floor 2 vehicle
        f2_exit = self.state_engine.record_exit(floor=2)
        self.assertIsNotNone(f2_exit)
        self.assertEqual(f2_exit["floor"], 2)
        self.assertEqual(f2_exit["plate_number"], "MH02BB2222")
        self.assertEqual(self.state_engine.slots[f2_entry["assigned_slot"]]["status"], "AVAILABLE")
        self.assertEqual(f2_exit["exit_route"]["origin_floor"], 2)

    def test_accessibility_scoring_f1_hierarchy(self):
        """Verify Floor 1 6-slot layout accessibility scores follow the driving distance hierarchy"""
        s01_score = self.allocator.slots_metadata["F1-S01"]["distance_score"]
        s03_score = self.allocator.slots_metadata["F1-S03"]["distance_score"]
        s02_score = self.allocator.slots_metadata["F1-S02"]["distance_score"]
        s04_score = self.allocator.slots_metadata["F1-S04"]["distance_score"]
        s05_score = self.allocator.slots_metadata["F1-S05"]["distance_score"]
        s06_score = self.allocator.slots_metadata["F1-S06"]["distance_score"]
        
        self.assertGreater(s01_score, s03_score)
        self.assertGreater(s03_score, s02_score)
        self.assertGreater(s02_score, s04_score)
        self.assertGreater(s04_score, s05_score)
        self.assertGreater(s05_score, s06_score)

        # Allocate on clean slate: S01 gets top priority
        res = self.allocator.allocate(occupancy_map={}, vehicle_type="car")
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res["slot_id"], "F1-S01")

        # When S01 is occupied, S03 gets priority next
        res2 = self.allocator.allocate(occupancy_map={"F1-S01": {"status": "OCCUPIED"}}, vehicle_type="car")
        self.assertIsNotNone(res2)
        assert res2 is not None
        self.assertEqual(res2["slot_id"], "F1-S03")

        # When S01 and S03 are occupied, S02 gets priority
        res3 = self.allocator.allocate(occupancy_map={"F1-S01": {"status": "OCCUPIED"}, "F1-S03": {"status": "OCCUPIED"}}, vehicle_type="car")
        self.assertIsNotNone(res3)
        assert res3 is not None
        self.assertEqual(res3["slot_id"], "F1-S02")

    def test_floor_2_ramp_distance_impact(self):
        """Verify Floor 2 accessibility scores reflect the slope ramp travel impedance"""
        f1_s01 = self.allocator.slots_metadata["F1-S01"]["distance_score"]
        f2_s01 = self.allocator.slots_metadata["F2-S01"]["distance_score"]
        self.assertGreater(f1_s01, f2_s01)

        # S02 on Floor 2 should also beat S03 on Floor 2
        f2_s02 = self.allocator.slots_metadata["F2-S02"]["distance_score"]
        f2_s03 = self.allocator.slots_metadata["F2-S03"]["distance_score"]
        self.assertGreater(f2_s02, f2_s03)

    def test_monotonic_distance_scoring(self):
        """Verify all 56 slots have scores between 10 and 100 with valid metadata"""
        for sid, meta in self.allocator.slots_metadata.items():
            score = meta["distance_score"]
            self.assertGreaterEqual(score, 10)
            self.assertLessEqual(score, 100)
            self.assertIn("route_distance_px", meta)
            self.assertGreater(meta["route_distance_px"], 0)

    def test_level_wise_allocation_order(self):
        """Verify sequential allocations strictly follow the requested level-wise priority order"""
        expected_f1_order = [
            "F1-S01", "F1-S03", "F1-S02", "F1-S04", "F1-S05", "F1-S06"
        ]
        occupancy = {}
        allocated = []
        for _ in range(6):
            res = self.allocator.allocate(occupancy_map=occupancy, vehicle_type="car")
            self.assertIsNotNone(res)
            assert res is not None
            slot_id = res["slot_id"]
            allocated.append(slot_id)
            occupancy[slot_id] = {"status": "ALLOCATED"}

        self.assertEqual(allocated, expected_f1_order)

        # After F1 is full, the next allocation spills over to Floor 2
        f2_next = self.allocator.allocate(occupancy_map=occupancy, vehicle_type="car")
        self.assertIsNotNone(f2_next)
        assert f2_next is not None
        self.assertTrue(str(f2_next["slot_id"]).startswith("F2-"))

        # Even with is_ev or truck flags, allocation follows unified level-wise order without skipping
        ev_alloc = self.allocator.allocate(occupancy_map={}, is_ev=True)
        self.assertIsNotNone(ev_alloc)
        assert ev_alloc is not None
        self.assertEqual(ev_alloc["slot_id"], "F1-S01")

        large_alloc = self.allocator.allocate(occupancy_map={}, vehicle_type="truck")
        self.assertIsNotNone(large_alloc)
        assert large_alloc is not None
        self.assertEqual(large_alloc["slot_id"], "F1-S01")

    def test_a_star_pathfinding_all_56_slots(self):
        """Verify A* route calculation generates valid driving paths for every slot"""
        for sid in self.allocator.slots_metadata.keys():
            route = self.router.find_shortest_path("ENTRANCE", sid)
            self.assertIsNotNone(route)
            self.assertIn("ENTRANCE", route["path_nodes"])
            self.assertIn(sid, route["path_nodes"])
            self.assertGreater(len(route["coordinates"]), 2)
            self.assertGreater(route["distance_pixels"], 0)

if __name__ == "__main__":
    unittest.main()


