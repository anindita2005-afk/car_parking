from fastapi.testclient import TestClient
from app.main import app
from app.core.database import Base, engine

# Create the database for testing
Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_register_vehicle_entry():
    payload = {
        "plate_number": "ABC1234",
        "vehicle_type": "2",
        "camera_id": "CAM_01",
        "confidence": "0.85"
    }
    
    response = client.post("/api/entry", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["plate_number"] == "ABC1234"
    assert data["camera_id"] == "CAM_01"
    assert "id" in data
    assert "entry_time" in data
