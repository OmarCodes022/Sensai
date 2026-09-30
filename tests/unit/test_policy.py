from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from sensai.policy import (
    ApprovedClaim,
    DataClass,
    Direction,
    PolicyAction,
    PolicyDecision,
    PolicySpec,
    PrivacyRule,
)


@pytest.fixture
def fictional_policy():
    return PolicySpec(
        privacy_rules=(
            PrivacyRule(
                Direction.INPUT, DataClass.PUBLIC_BRAND, PolicyAction.ALLOW, "approved_brand"
            ),
            PrivacyRule(
                Direction.INPUT,
                DataClass.AGGREGATE_METRIC,
                PolicyAction.ALLOW,
                "sourced_aggregate",
            ),
            PrivacyRule(
                Direction.INPUT, DataClass.PRIVATE_DM, PolicyAction.REFUSE, "raw_dm"
            ),
            PrivacyRule(
                Direction.INPUT, DataClass.SANITIZED_DM, PolicyAction.ALLOW, "sanitized_dm"
            ),
            PrivacyRule(
                Direction.INPUT,
                DataClass.DIRECT_IDENTIFIER,
                PolicyAction.REDACT,
                "remove_identifier",
                "[redacted]",
            ),
            PrivacyRule(
                Direction.INPUT,
                DataClass.SENSITIVE_DETAIL,
                PolicyAction.REFUSE,
                "sensitive_dm",
            ),
            PrivacyRule(
                Direction.OUTPUT,
                DataClass.DIRECT_IDENTIFIER,
                PolicyAction.REDACT,
                "remove_identifier",
                "[redacted]",
            ),
            PrivacyRule(
                Direction.OUTPUT,
                DataClass.SENSITIVE_DETAIL,
                PolicyAction.REFUSE,
                "sensitive_output",
            ),
            PrivacyRule(
                Direction.OUTPUT, DataClass.REVIEW_DRAFT, PolicyAction.ALLOW, "validated_draft"
            ),
        ),
        approved_claims=(
            ApprovedClaim(
                "fictional_ingredient_01",
                "Dew Gel contains glycerin.",
                "fictional-reviewed-formula-v1",
                date(2026, 1, 1),
                date(2026, 12, 31),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("direction", "data_class", "expected_action", "replacement"),
    [
        (Direction.INPUT, DataClass.PUBLIC_BRAND, PolicyAction.ALLOW, None),
        (Direction.INPUT, DataClass.AGGREGATE_METRIC, PolicyAction.ALLOW, None),
        (Direction.INPUT, DataClass.PRIVATE_DM, PolicyAction.REFUSE, None),
        (Direction.INPUT, DataClass.SANITIZED_DM, PolicyAction.ALLOW, None),
        (Direction.INPUT, DataClass.DIRECT_IDENTIFIER, PolicyAction.REDACT, "[redacted]"),
        (Direction.INPUT, DataClass.SENSITIVE_DETAIL, PolicyAction.REFUSE, None),
        (Direction.OUTPUT, DataClass.DIRECT_IDENTIFIER, PolicyAction.REDACT, "[redacted]"),
        (Direction.OUTPUT, DataClass.SENSITIVE_DETAIL, PolicyAction.REFUSE, None),
        (Direction.OUTPUT, DataClass.REVIEW_DRAFT, PolicyAction.ALLOW, None),
    ],
)
def test_fictional_privacy_rule_configuration(
    fictional_policy, direction, data_class, expected_action, replacement
):
    rules = {
        (rule.direction, rule.data_class): rule for rule in fictional_policy.privacy_rules
    }
    rule = rules[direction, data_class]
    assert rule.action is expected_action
    assert rule.replacement == replacement
    assert rule.reason_code


def test_unrecognized_data_and_unsupported_claims_default_to_refusal(fictional_policy):
    assert fictional_policy.unknown_data_action is PolicyAction.REFUSE
    assert fictional_policy.unsupported_claim_action is PolicyAction.REFUSE
    assert fictional_policy.approved_claims == (
        ApprovedClaim(
            "fictional_ingredient_01",
            "Dew Gel contains glycerin.",
            "fictional-reviewed-formula-v1",
            date(2026, 1, 1),
            date(2026, 12, 31),
        ),
    )
    with pytest.raises(TypeError):
        PolicySpec(
            privacy_rules=(),
            approved_claims=(),
            unsupported_claim_action=PolicyAction.ALLOW,
        )


def test_policy_spec_can_be_configured_without_changing_defaults(fictional_policy):
    alternate = PolicySpec(
        privacy_rules=fictional_policy.privacy_rules
        + (
            PrivacyRule(
                Direction.OUTPUT,
                DataClass.AGGREGATE_METRIC,
                PolicyAction.ALLOW,
                "sourced_aggregate",
            ),
        ),
        approved_claims=(),
    )
    assert len(alternate.privacy_rules) == len(fictional_policy.privacy_rules) + 1
    assert alternate.approved_claims == ()
    assert alternate.unsupported_claim_action is PolicyAction.REFUSE
    with pytest.raises(FrozenInstanceError):
        fictional_policy.approved_claims = ()


def test_sanitized_decision_is_only_a_handoff_record():
    decision = PolicyDecision(
        PolicyAction.REDACT,
        "remove_identifier",
        rule_id="input_identifier",
        replacement="[redacted]",
    )
    assert decision.action is PolicyAction.REDACT
    assert decision.reason_code == "remove_identifier"
    assert decision.replacement == "[redacted]"
    with pytest.raises(FrozenInstanceError):
        decision.action = PolicyAction.ALLOW
