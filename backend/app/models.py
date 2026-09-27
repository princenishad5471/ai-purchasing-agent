"""Pydantic models for AI Purchasing Agent"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class DecisionType(str, Enum):
    ACCEPT = "ACCEPT"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    INVESTIGATE_FURTHER = "INVESTIGATE_FURTHER"


class POStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecommendationStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    INVESTIGATING = "investigating"
    ACCEPTED = "accepted"
    MODIFIED = "modified"
    REJECTED = "rejected"
    ESCALATED = "escalated"


# Request/Response Models
class PurchaseRecommendation(BaseModel):
    recommendation_id: Optional[str] = None
    product_id: str
    product_name: str
    node_id: str
    node_name: str
    recommended_quantity: int
    recommended_supplier: str
    recommendation_source: str = "system_auto"
    status: RecommendationStatus = RecommendationStatus.PENDING_REVIEW
    created_at: Optional[datetime] = None


class InventoryInfo(BaseModel):
    current_stock: int
    reserved_stock: int
    available_stock: int
    reorder_point: int
    safety_stock: int


class DemandForecast(BaseModel):
    daily_avg: float
    forecast_7d: float
    forecast_14d: float
    forecast_30d: float


class OpenPO(BaseModel):
    po_id: str
    quantity: int
    expected_delivery: str
    status: str


class SupplierInfo(BaseModel):
    supplier_id: str
    name: str
    moq: int
    max_order_qty: int
    lead_time_days: int
    available_quantity: int
    unit_price: float
    reliability_score: float


class StorageInfo(BaseModel):
    capacity: int
    current_usage: int
    available: int
    product_allocation: int


class BudgetInfo(BaseModel):
    node_budget: float
    spent_this_month: float
    remaining: float
    product_category_budget: float


class SalesVelocity(BaseModel):
    last_7d_daily_avg: float
    last_30d_daily_avg: float
    trend: str


class InvestigationResult(BaseModel):
    recommendation_id: str
    inventory: InventoryInfo
    demand: DemandForecast
    open_orders: List[OpenPO]
    supplier_info: SupplierInfo
    storage: StorageInfo
    budget: BudgetInfo
    sales_velocity: SalesVelocity
    inventory_coverage_days: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentDecision(BaseModel):
    recommendation_id: str
    decision: DecisionType
    final_quantity: int
    final_supplier: str
    reasoning: str
    evidence: List[str]
    confidence: float
    requires_approval: bool
    approval_reason: Optional[str] = None
    llm_model: str
    llm_prompt: Optional[str] = None
    llm_response: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ValidationResult(BaseModel):
    passed: bool
    rule: str
    message: str = ""
    value: Optional[Any] = None
    threshold: Optional[Any] = None
    requires_escalation: bool = False
    warning: bool = False


class ConstraintValidationResult(BaseModel):
    po_id: Optional[str] = None
    recommendation_id: str
    validations: Dict[str, ValidationResult]
    all_passed: bool
    failed_rules: List[str]
    requires_escalation: bool
    escalation_reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class POLineItem(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    unit_price: float
    total_price: float


class PurchaseOrder(BaseModel):
    po_id: str
    recommendation_id: str
    node_id: str
    supplier_id: str
    supplier_name: str
    line_items: List[POLineItem]
    total_amount: float
    expected_delivery: str
    status: POStatus
    created_by: str = "agent"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    validated_at: Optional[datetime] = None


class PostActionValidation(BaseModel):
    po_id: str
    checks: Dict[str, bool]
    failures: List[str]
    retry_count: int = 0
    escalated: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ReviewRequest(BaseModel):
    recommendation_id: str


class ReviewResponse(BaseModel):
    recommendation_id: str
    investigation: InvestigationResult
    decision: AgentDecision
    constraint_validation: ConstraintValidationResult
    purchase_order: Optional[PurchaseOrder] = None
    post_validation: Optional[PostActionValidation] = None
    trace: List[Dict[str, Any]]
