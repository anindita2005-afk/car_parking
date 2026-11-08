from typing import Optional, List
from datetime import datetime
from sqlalchemy import Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.core.database import Base

class ParkingSlot(Base):
    """
    Parking Slot / Plot Table.
    Maintains real-time availability: FREE, OCCUPIED, RESERVED, ALLOCATED, RESTRICTED.
    """
    __tablename__ = "parking_slots"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True) # e.g. "F1-S01", "F2-S01"
    floor: Mapped[int] = mapped_column(Integer, default=1, index=True)   # 1 for First Floor (F1), 2 for Second Floor (F2)
    slot_number: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    slot_type: Mapped[str] = mapped_column(String, default="STANDARD")   # STANDARD, LARGE, EV, RESERVED, RESTRICTED
    status: Mapped[str] = mapped_column(String, default="FREE")          # FREE, OCCUPIED, RESERVED, ALLOCATED, RESTRICTED
    current_vehicle_plate: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    current_track_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_ev: Mapped[bool] = mapped_column(Boolean, default=False)
    distance_score: Mapped[int] = mapped_column(Integer, default=80)
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=80)
    height: Mapped[int] = mapped_column(Integer, default=120)
    occupied_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    # Relationship to sessions
    sessions: Mapped[List["ParkingSession"]] = relationship("ParkingSession", back_populates="slot_rel")

class ParkingSession(Base):
    """
    Vehicle Parking Session & Billing Record Table.
    Tracks license plate, entry time, exit time, assigned slot, duration, and tariff fee.
    """
    __tablename__ = "parking_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    vehicle_plate: Mapped[str] = mapped_column(String, index=True, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String, default="car")     # car, ev, truck, suv, bus, motorcycle
    is_ev: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_slot: Mapped[Optional[str]] = mapped_column(String, ForeignKey("parking_slots.id"), nullable=True)
    track_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    camera_id: Mapped[str] = mapped_column(String, default="CAM_01")
    
    entry_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    entry_timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_timestamp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    duration_formatted: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    fee_inr: Mapped[float] = mapped_column(Float, default=20.0)
    
    status: Mapped[str] = mapped_column(String, default="ENTERING") # ENTERING, PARKED, COMPLETED, BYPASS
    ocr_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    route_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    slot_rel: Mapped[Optional[ParkingSlot]] = relationship("ParkingSlot", back_populates="sessions")

class SystemLog(Base):
    """
    Audit and Activity Log Table.
    """
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    event_type: Mapped[str] = mapped_column(String, default="INFO")
    message: Mapped[str] = mapped_column(String, nullable=False)
    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
