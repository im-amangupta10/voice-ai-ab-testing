import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator
from db.models import ExperimentStatus

class VariantType(str, Enum):
    FULL_PROMPT = "FULL_PROMPT"
    DELTA_PATCH = "DELTA_PATCH"

class VariantCreate(BaseModel):
    key: str = Field(..., description="Variant identifier, e.g. 'A' or 'B'")
    name: str = Field(..., description="Readable label for variant")
    variant_type: VariantType = Field(default=VariantType.FULL_PROMPT)
    content: str = Field(..., description="Prompt text or instruction delta")
    traffic_weight: float = Field(..., ge=0.0, le=1.0, description="Traffic proportion, e.g. 0.90 for A, 0.10 for B")

class VariantResponse(VariantCreate):
    id: str
    experiment_id: str

    class Config:
        from_attributes = True

class ExperimentCreate(BaseModel):
    id: Optional[str] = Field(None, description="Optional unique ID, will auto-generate if omitted")
    name: str = Field(..., min_length=3, description="Descriptive experiment title")
    description: Optional[str] = None
    base_prompt: str = Field(..., description="Original baseline prompt")
    variants: List[VariantCreate] = Field(..., min_length=2, max_length=2, description="Variant A (control) & Variant B (challenger)")
    
    window_hours: int = Field(default=48, ge=1, description="Duration in hours to run test")
    min_sample_per_variant: int = Field(default=100, ge=5, description="Minimum calls required per variant before declaring winner")
    confidence_level: float = Field(default=0.95, ge=0.80, le=0.999)
    primary_metric: str = Field(default="meeting_fixed_rate")
    secondary_metric: str = Field(default="avg_call_duration_sec")
    guardrail_max_delta: float = Field(default=30.0, description="Max allowed increase in secondary metric")
    early_stop_threshold: float = Field(default=0.01, description="Threshold below which B is considered harmful")

    @model_validator(mode="after")
    def validate_variants_and_weights(self):
        keys = [v.key.upper() for v in self.variants]
        if "A" not in keys or "B" not in keys:
            raise ValueError("Experiment must define exactly Variant 'A' and Variant 'B'.")
        
        total_weight = sum(v.traffic_weight for v in self.variants)
        if abs(total_weight - 1.0) > 0.001:
            raise ValueError(f"Total variant traffic weights must sum to 1.0 (current sum: {total_weight:.3f})")
        return self

class ExperimentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    base_prompt: str
    window_hours: int
    min_sample_per_variant: int
    confidence_level: float
    primary_metric: str
    secondary_metric: str
    guardrail_max_delta: float
    early_stop_threshold: float
    created_at: datetime.datetime
    updated_at: Optional[datetime.datetime] = None
    concluded_at: Optional[datetime.datetime] = None
    variants: List[VariantResponse] = []

    class Config:
        from_attributes = True

class ExperimentStatusUpdate(BaseModel):
    action: str = Field(..., description="Action: 'START', 'PAUSE', 'CONCLUDE', 'STOP_EARLY', 'PROMOTE_B'")
    reason: Optional[str] = None
