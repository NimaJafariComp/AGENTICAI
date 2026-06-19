from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DecisionType(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


class Customer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    email: str
    risk_score: int = Field(ge=0, le=100)
    lifetime_value: float = Field(ge=0)
    notes: str


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    sku: str
    name: str
    category: str
    price: float = Field(ge=0)
    final_sale: bool
    delivered_at: date


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    customer_id: str
    order_date: date
    shipping_country: str
    payment_status: str
    total: float = Field(ge=0)
    items: list[OrderItem]


class CustomerSeedData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customers: list[Customer]


class OrderSeedData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orders: list[Order]


class DamagedDefectivePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible: bool
    special_window_days: int = Field(ge=0)
    requires_review_if_evidence_missing: bool


class SuspiciousClaimEscalationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    risk_score_threshold: int = Field(ge=0, le=100)
    inconsistent_claims_require_escalation: bool


class DecisionIdRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_for_terminal_actions: bool
    actions: list[str]


class PolicyFrontMatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_name: str
    policy_version: str
    currency: str
    return_window_days: int = Field(ge=0)
    final_sale_non_refundable: bool
    human_escalation_amount: float = Field(ge=0)
    damaged_defective: DamagedDefectivePolicy
    suspicious_claim_escalation: SuspiciousClaimEscalationPolicy
    decision_id_rules: DecisionIdRules


class RefundPolicyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: PolicyFrontMatter
    markdown_body: str


class RuntimeSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    customer_email: str | None = None
    created_at: datetime
    updated_at: datetime


class RuntimeTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    session_id: str
    event_type: str
    payload_json: str
    created_at: datetime


class RuntimeToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    session_id: str
    tool_name: str
    tool_input_json: str
    tool_output_json: str | None = None
    status: str
    created_at: datetime


class RuntimeFinalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    session_id: str
    decision_type: DecisionType
    used: bool
    request_fingerprint: str
    reason_codes_json: str
    created_at: datetime
    used_at: datetime | None = None


class CreateRuntimeSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    customer_email: str | None = None


class CreateRuntimeTraceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    session_id: str
    event_type: str
    payload: dict | list | str | int | float | bool | None


class CreateRuntimeToolCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    session_id: str
    tool_name: str
    tool_input: dict | list | str | int | float | bool | None
    tool_output: dict | list | str | int | float | bool | None = None
    status: str


class CreateRuntimeFinalDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    session_id: str
    decision_type: DecisionType
    request_fingerprint: str
    reason_codes: list[str]


class AppSeedData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customers: list[Customer]
    orders: list[Order]
    policy: RefundPolicyDocument


class DataSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_count: int = Field(ge=0)
    order_count: int = Field(ge=0)
    policy_name: str
    policy_version: str


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    customer_email: str
    customer_name: str
    order_id: str
    item_id: str
    issue_type: str
    claim_text: str
    requested_amount: float = Field(ge=0)
    evidence_notes: str | None = None
    evidence_provided: bool = False
    claim_inconsistent: bool = False


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_type: DecisionType
    reason_codes: list[str]
    policy_rules: list[str]
    explanation: str
    eligible: bool
    requires_human_review: bool


class AgentTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    status: str
    assistant_message: str
    missing_fields: list[str] = Field(default_factory=list)
    decision_type: str | None = None
    decision_id: str | None = None
    tool_outputs: dict[str, object] = Field(default_factory=dict)
