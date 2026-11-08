from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class VehicleEntry(Base):
    __tablename__ = "vehicle_entries"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String, index=True, nullable=False)
    vehicle_type = Column(String, nullable=True) # e.g., car, truck
    camera_id = Column(String, nullable=True)
    confidence = Column(String, nullable=True) # Storing confidence score
    assigned_slot = Column(String, nullable=True)
    entry_time = Column(DateTime(timezone=True), server_default=func.now())
