"""Typed, declarative privacy and product-claim policy handoff for a future gate."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Direction(str, Enum):
    INPUT = "input"
    OUTPUT = "output"


class DataClass(str, Enum):
    PUBLIC_BRAND = "public_brand"
    AGGREGATE_METRIC = "aggregate_metric"
    PRIVATE_DM = "private_dm"
    SANITIZED_DM = "sanitized_dm"
    REVIEW_DRAFT = "review_draft"
    DIRECT_IDENTIFIER = "direct_identifier"
    SENSITIVE_DETAIL = "sensitive_detail"


class PolicyAction(str, Enum):
    ALLOW = "allow"
    REDACT = "redact"
    REFUSE = "refuse"


@dataclass(frozen=True)
class PrivacyRule:
    direction: Direction
    data_class: DataClass
    action: PolicyAction
    reason_code: str
    replacement: str | None = None


@dataclass(frozen=True)
class ApprovedClaim:
    claim_id: str
    exact_text: str
    evidence_ref: str
    valid_from: date
    valid_until: date


@dataclass(frozen=True)
class PolicySpec:
    privacy_rules: tuple[PrivacyRule, ...]
    approved_claims: tuple[ApprovedClaim, ...]
    unknown_data_action: PolicyAction = field(default=PolicyAction.REFUSE, init=False)
    unsupported_claim_action: PolicyAction = field(default=PolicyAction.REFUSE, init=False)


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    reason_code: str
    rule_id: str | None = None
    replacement: str | None = None
