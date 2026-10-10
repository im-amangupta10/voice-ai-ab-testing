import datetime
from sqlalchemy import (
    Column, String, Float, Integer, DateTime, Boolean, ForeignKey, Index, Text, Enum
)
from sqlalchemy.orm import relationship
from db.connection import Base
import enum

class ExperimentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    CONCLUDED = "CONCLUDED"
    STOPPED_EARLY = "STOPPED_EARLY"

class ExperimentModel(Base):
    __tablename__ = "experiments"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), default=ExperimentStatus.DRAFT.value, nullable=False, index=True)
    base_prompt = Column(Text, nullable=False)
    
    # Configuration
    window_hours = Column(Integer, default=48, nullable=False)
    min_sample_per_variant = Column(Integer, default=100, nullable=False)
    confidence_level = Column(Float, default=0.95, nullable=False)
    primary_metric = Column(String(64), default="meeting_fixed_rate", nullable=False)
    primary_disposition = Column(String(128), default="BL Enriched", nullable=False)
    secondary_metric = Column(String(64), default="avg_call_duration_sec", nullable=False)
    guardrail_max_delta = Column(Float, default=30.0, nullable=False) # e.g. max allowed sec duration rise
    early_stop_threshold = Column(Float, default=0.01, nullable=False) # P(B>A) <= 0.01

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    deployed_variant_key = Column(String(8), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    concluded_at = Column(DateTime, nullable=True)

    # Relationships
    variants = relationship("VariantModel", back_populates="experiment", cascade="all, delete-orphan")
    events = relationship("CallEventModel", back_populates="experiment", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLogModel", back_populates="experiment", cascade="all, delete-orphan")

class VariantModel(Base):
    __tablename__ = "variants"

    id = Column(String(64), primary_key=True, index=True)
    experiment_id = Column(String(64), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(8), nullable=False) # 'A' or 'B'
    name = Column(String(128), nullable=False)
    variant_type = Column(String(32), default="FULL_PROMPT", nullable=False) # FULL_PROMPT | DELTA_PATCH
    content = Column(Text, nullable=False) # The prompt or diff patch
    traffic_weight = Column(Float, nullable=False) # e.g., 0.90 or 0.10

    experiment = relationship("ExperimentModel", back_populates="variants")

class CallEventModel(Base):
    __tablename__ = "call_events"

    id = Column(String(64), primary_key=True, index=True)
    experiment_id = Column(String(64), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_key = Column(String(8), nullable=False) # 'A' or 'B'
    caller_id = Column(String(128), nullable=False, index=True)
    call_id = Column(String(128), nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    
    disposition = Column(String(64), nullable=False)
    call_duration_sec = Column(Float, nullable=False)
    duration_observed = Column(Boolean, default=False, nullable=False)
    meeting_fixed = Column(Integer, default=0, nullable=False) # 1 if meeting fixed else 0

    experiment = relationship("ExperimentModel", back_populates="events")

    __table_args__ = (
        Index("idx_exp_variant_timestamp", "experiment_id", "variant_key", "timestamp"),
        Index("idx_exp_caller", "experiment_id", "caller_id"),
    )

class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(String(64), primary_key=True, index=True)
    experiment_id = Column(String(64), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(64), nullable=False) # CREATED, STARTED, PAUSED, PROMOTED, EARLY_STOPPED
    details = Column(Text, nullable=True) # JSON metadata or evidence snapshot
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    experiment = relationship("ExperimentModel", back_populates="audit_logs")
