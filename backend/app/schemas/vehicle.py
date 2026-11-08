from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class VehicleEntryCreate(BaseModel):
    plate_number: str
    vehicle_type: Optional[str] = None
    camera_id: Optional[str] = None
    confidence: Optional[str] = None
    needs_ev: Optional[bool] = False

class VehicleEntryResponse(BaseModel):
    id: int
    plate_number: str
    vehicle_type: Optional[str]
    camera_id: Optional[str]
    confidence: Optional[str]
    assigned_slot: Optional[str]
    entry_time: datetime

    class Config:
        orm_mode = True
