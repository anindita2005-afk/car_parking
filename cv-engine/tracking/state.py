class TrackingState:
    def __init__(self):
        # Maps track_id -> dict with plate text, confidence, and reported flag
        self.identities = {}

    def get_identity(self, track_id):
        return self.identities.get(track_id)

    def set_identity(self, track_id, plate_text, confidence):
        if track_id not in self.identities:
            self.identities[track_id] = {
                "plate_text": plate_text,
                "confidence": confidence,
                "reported": False
            }
        else:
            # Only update if the new read is significantly better
            if confidence > self.identities[track_id]["confidence"]:
                self.identities[track_id]["plate_text"] = plate_text
                self.identities[track_id]["confidence"] = confidence

    def mark_reported(self, track_id):
        if track_id in self.identities:
            self.identities[track_id]["reported"] = True

    def is_reported(self, track_id):
        if track_id in self.identities:
            return self.identities[track_id]["reported"]
        return False
