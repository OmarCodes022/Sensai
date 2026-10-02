# Phase 1 privacy and product-claim policy handoff (T07)

This is a **configurable policy specification**, not an active classifier,
redactor, validation gate, four-output workflow or optional product feature.
Enforcement belongs to T38. Brand-specific facts and actual evidence may be
refined independently; every example below is fictional and is not an
approval of a real skincare claim.

`prompts/system.txt` now expresses these boundaries as model instructions.
This does not enforce the policy or sanitize inputs before generation.
[The T10 manual runner](../testing/adversarial-testing.md) lets Diana test and record
the current model's behavior without claiming that a validation gate exists.

## Decisions for inputs and outputs

`src/sensai/core/policy.py` provides immutable typed `PolicySpec`, `PrivacyRule`,
`ApprovedClaim`, and `PolicyDecision` handoff records. Rules specify a
`Direction` (input or output), `DataClass`, `PolicyAction`, and reason code;
a redact rule also supplies a replacement marker. An approved claim records
the **exact** permitted wording, evidence reference, and effective dates.
The consumer of this spec, not this module, must classify content, validate
sources and dates, apply decisions and prevent release. Rules are
configurable for a brand, but the product's release boundary is not a
permission to opt out of privacy or approval. Unknown-data and
unsupported-claim refusal are fixed defaults in the handoff, not
configurable claim permissions.

| Fictional context | Decision | Required handling |
| --- | --- | --- |
| Input: Serein Studio's approved voice brief or complete aggregate reach counts for the stated week | **Allow** | Use only with verified provenance, time window and authorized access; do not infer claims from the voice brief. |
| Input: a DM asking “What is the texture of Dew Gel?” alongside `[customer name]` and `[handle]` placeholders | **Redact** | Locally remove direct/indirect identifiers, contact details, order IDs and identifying quotes before generation; retain only the generic product question, not the raw DM or real message ID in the output. |
| Input: a raw DM with identifiers not yet sanitized | **Refuse** | Do not pass raw private content to generation. Only the locally sanitized question is eligible to be classified as `SANITIZED_DM` and allowed. |
| Input: a DM describing a customer's medical condition or a minor | **Refuse** | Do not feed it into generation or summarize it in artifacts; route it outside this product flow without copying the private detail into logs. |
| Output: “Dew Gel contains glycerin.” | **Allow only if approved** | Hypothetical example: exact text is in the fictional, in-date claim register and a verified fictional formula/label record supports it. Approval of a claim does not waive output privacy checks. |
| Output: “Dew Gel cures eczema.” or a claim with no current supporting record | **Refuse** | Reject the affected draft/suggestion for review; never invent supporting evidence or quietly reframe it as an approved claim. No medical-treatment claims from a brand voice brief. |
| Output: a suggestion repeating `[customer name]` or a weekly report with a raw DM quote | **Redact or refuse** | Remove the identifiers if a safe generic suggestion remains; refuse the whole artifact if details cannot be removed reliably. No personal-level analytics in private exports either. |

`ALLOW` is valid only for its classified class/direction and verified
provenance. `REDACT` replaces sensitive spans with the configured marker
**before** model input or saved/exported output; it is not consent to retain
raw DMs. `REFUSE` (the deny action) stops the affected payload/artifact and
records a reason code without private content. Ambiguous classification,
unknown classes, uncertain redaction, unsupported or expired claims, and
unverified provenance default to refusal. Where rules overlap, refusal wins
over redaction, which wins over allow. A redacted DM that still carries a
medical detail is refused; a supported claim containing an identifier is
still redacted or refused. T38 must implement these rules and test that
unknown content cannot fall through as allowed.

The same checks apply on the **input** side (before any model call) and the
**output** side (before saving and again before any release). Missing source
data is not an empty data set; invalid, out-of-window or denominator-free
metrics cannot become report facts. Zero reach may produce a sourced `n/a`,
not a fabricated engagement rate. Never use private messages as evidence
for a product claim. A private/local creator-controlled export is automatic
**only after validation**; its storage must not be public. An external send,
public link, DM send or publication requires separate explicit approval
bound to the **exact content and destination**. A change to either requires
new approval. Scheduled runs prepare drafts only, not remote schedules or
publications. These are requirements for a later gate, not guarantees of
the present runtime.

Example typed handoff for T38, with **simulated** evidence rather than real
brand material:

```python
from datetime import date
from sensai.core.policy import (
    ApprovedClaim, DataClass, Direction, PolicyAction, PolicySpec, PrivacyRule,
)

fictional_policy = PolicySpec(
    privacy_rules=(
        PrivacyRule(Direction.INPUT, DataClass.PUBLIC_BRAND, PolicyAction.ALLOW, "approved_brand"),
        PrivacyRule(Direction.INPUT, DataClass.AGGREGATE_METRIC, PolicyAction.ALLOW, "sourced_aggregate"),
        PrivacyRule(Direction.INPUT, DataClass.PRIVATE_DM, PolicyAction.REFUSE, "raw_dm"),
        PrivacyRule(Direction.INPUT, DataClass.SANITIZED_DM, PolicyAction.ALLOW, "sanitized_dm"),
        PrivacyRule(Direction.INPUT, DataClass.DIRECT_IDENTIFIER, PolicyAction.REDACT, "remove_identifier", "[redacted]"),
        PrivacyRule(Direction.INPUT, DataClass.SENSITIVE_DETAIL, PolicyAction.REFUSE, "sensitive_dm"),
        PrivacyRule(Direction.OUTPUT, DataClass.REVIEW_DRAFT, PolicyAction.ALLOW, "validated_draft"),
        PrivacyRule(Direction.OUTPUT, DataClass.DIRECT_IDENTIFIER, PolicyAction.REDACT, "remove_identifier", "[redacted]"),
        PrivacyRule(Direction.OUTPUT, DataClass.SENSITIVE_DETAIL, PolicyAction.REFUSE, "sensitive_output"),
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
```

That record declares policy only: constructing it does not inspect text,
verify the evidence reference, redact, refuse, export, send or publish
anything. The sample claim must not be treated as approved outside this
fictional scenario. T38 should consume the typed spec and return sanitized
`PolicyDecision` reason codes without storing raw personal content.
