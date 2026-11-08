import json
import os

class SlotAllocator:
    """
    Intelligent Parking Slot Allocator for Multi-Floor Parking Facility.
    Evaluates slot candidates using predefined roadway accessibility scores
    derived from physical driving distance and turn impedance from ENTRANCE.
    All bays are unified general parking bays with specialized EV charging and
    vehicle sizing compatibility preferences.
    """
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "config.json")
        with open(config_path, 'r') as f:
            self.slots_metadata = json.load(f)

    def allocate(self, occupancy_map=None, vehicle_type="general", is_ev=False, is_reserved=False, plate_number=None, preferred_floor=None):
        """
        occupancy_map: dict of slot_id -> {"status": "AVAILABLE"|"OCCUPIED"|"ALLOCATED"|"UNAVAILABLE"}
        Returns dict: {"slot_id": str, "score": float, "slot_type": str, "reason": str, "alternatives": list}
        Allocates the optimal parking bay ranked strictly by predefined accessibility distance_score.
        """
        if occupancy_map is None:
            occupancy_map = {}

        candidates = []

        for slot_id, meta in self.slots_metadata.items():
            slot_floor = meta.get("floor", 1)
            bay_type = meta.get("bay_type", meta.get("type", "STANDARD"))
            slot_is_ev = meta.get("is_ev", False)
            dist_score = meta.get("distance_score", 50)
            
            slot_status = occupancy_map.get(slot_id, {}).get("status", "AVAILABLE") if occupancy_map else "AVAILABLE"

            # 1. Skip occupied, allocated or unavailable slots
            if slot_status in ["OCCUPIED", "ALLOCATED", "RESERVED_FOR_ENTRY", "UNAVAILABLE"]:
                continue
            if meta.get("type") == "RESTRICTED" or bay_type == "RESTRICTED":
                continue

            # 2. Score calculation initialized with predefined distance_score
            score = float(dist_score)

            # Floor priority preference bonus
            if preferred_floor is not None and slot_floor == preferred_floor:
                score += 200

            # EV charging bay preferences and restrictions
            if is_ev:
                if slot_is_ev or bay_type == "EV":
                    score += 50  # Strong preference for EV bays
            else:
                if slot_is_ev or bay_type == "EV":
                    score -= 30  # Preserve EV bays for EV vehicles unless standard slots full

            # Vehicle size compatibility
            is_large = vehicle_type and str(vehicle_type).lower() in ["truck", "large", "suv_xl", "bus"]
            if is_large:
                if bay_type == "LARGE":
                    score += 40  # Preference for spacious bays
            else:
                if bay_type == "LARGE":
                    score -= 10  # Preserve large bays for large vehicles

            # Reserved slot restrictions
            if not is_reserved and bay_type == "RESERVED":
                score -= 40

            # Construct explainable reason maintaining General system compliance
            if is_ev and (slot_is_ev or bay_type == "EV"):
                reason = f"Optimal General EV Charging Bay (Proximity score: {dist_score})"
            elif is_large and bay_type == "LARGE":
                reason = f"Optimal General Large Bay (Proximity score: {dist_score})"
            else:
                reason = f"Optimal General Parking Bay (Proximity score: {dist_score})"

            candidates.append({
                "slot_id": slot_id,
                "score": score,
                "dist_score": dist_score,
                "slot_type": "GENERAL",
                "reason": reason
            })

        if not candidates:
            return None

        # Sort descending by score, tie-break by dist_score
        candidates.sort(key=lambda x: (x["score"], x["dist_score"]), reverse=True)
        best = candidates[0]

        return {
            "slot_id": best["slot_id"],
            "score": best["score"],
            "slot_type": "GENERAL",
            "reason": best["reason"],
            "alternatives": [c["slot_id"] for c in candidates[1:3]]
        }
