"""The rules: patterns by data class, actions by direction, and the brand file's claims.

Refuse wins over redact, and redact over allow (docs/product/privacy-and-claims.md).
Decisions carry reason codes; the private text itself never appears in them.
"""
import json
import re
from dataclasses import dataclass
from datetime import date

from sensai.core.policy import ApprovedClaim, DataClass, PolicyAction
from sensai.core.ports import GuardrailDecision

REDACTED = "[redacted]"
PATTERNS: dict[str, list[str]] = {
    "email": [r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"],
    "phone": [r"(?<![\w-])\+?\d[\d .()-]{7,}\d(?![\w-])"],
    "handle": [r"(?<![\w@.])@[A-Za-z0-9_][A-Za-z0-9_.]{1,29}"],
    DataClass.UNSAFE_REQUEST.value: [
        r"\b(?:ignore|disregard|forget)\b.{0,40}\b(?:previous|prior|above|earlier|all|your)\b.{0,20}\b(?:instructions|rules|prompts?)\b",
        r"\b(?:reveal|print|show|repeat|leak)\b.{0,30}\b(?:system prompt|hidden instructions|your instructions)\b",
        r"\byou are now\b", r"\bdeveloper mode\b", r"\bjailbreak\b"],
    DataClass.SENSITIVE_DETAIL.value: [
        r"\bpregnan\w*", r"\bbreast-?feeding\b", r"\bmedications?\b", r"\bdiagnos\w*", r"\bprescri\w*",
        r"\b(?:my|her|his) (?:doctor|dermatologist)\b", r"\bchemotherapy\b",
        r"\b(?:i|she|he|they) (?:have|has) (?:eczema|psoriasis|rosacea|dermatitis|cancer|diabetes)\b"],
    "claim_word": [
        r"\bcures?\b", r"\bcured\b", r"\bheals?\b", r"\btreats\b",
        r"\btreat (?:acne|eczema|psoriasis|rosacea|dermatitis|wrinkles|scars)\b",
        r"\bclinically (?:proven|tested)\b", r"\bguaranteed?\b", r"\beliminates?\b", r"\bmedical[- ]grade\b"],
}
IDENTIFIERS = ("email", "phone", "handle")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# What each class does in each direction (the rules file may change these).
ACTIONS = {
    "input": {DataClass.UNSAFE_REQUEST.value: "refuse", DataClass.SENSITIVE_DETAIL.value: "refuse",
              "email": "redact", "phone": "redact", "handle": "redact"},
    "output": {"email": "redact", "phone": "redact", "handle": "redact"},
}
MESSAGES = {
    DataClass.UNSAFE_REQUEST.value: "This message looks like an attempt to change Sensai's rules. It was not sent to the model.",
    DataClass.SENSITIVE_DETAIL.value: "This message mentions a personal health detail. It was not sent to the model.",
}


class GuardrailConfigError(ValueError):
    """The rules file or the brand file cannot be used."""


@dataclass(frozen=True)
class Claims:
    approved: tuple[ApprovedClaim, ...] = ()
    blocked: tuple[tuple[str, str], ...] = ()  # (claim id, text) of claims not approved or out of date


class Guardrail:
    """GuardrailPort: inspect(text, "input" | "output") -> GuardrailDecision(allowed, text, reason)."""

    def __init__(self, patterns=None, actions=None, claims: Claims = Claims()):
        source = patterns or PATTERNS
        self.patterns = {name: [re.compile(p, re.IGNORECASE) for p in items] for name, items in source.items()}
        self.actions = actions or ACTIONS
        self.claims = claims

    def _found(self, name: str, text: str) -> list[re.Match]:
        found = [m for pattern in self.patterns.get(name, ()) for m in pattern.finditer(text)]
        if name == "phone":  # Dates and short numbers are not phone numbers.
            found = [m for m in found if sum(c.isdigit() for c in m.group()) >= 9 and not ISO_DATE.fullmatch(m.group())]
        return found

    def _redact(self, text: str, direction: str) -> tuple[str, list[str]]:
        classes = []
        for name in IDENTIFIERS:
            if self.actions[direction].get(name) != "redact":
                continue
            spans = self._found(name, text)
            if spans:
                classes.append(name)
                for m in sorted(spans, key=lambda m: m.start(), reverse=True):
                    text = text[:m.start()] + REDACTED + text[m.end():]
        return text, classes

    def inspect(self, text: str, direction: str) -> GuardrailDecision:
        for name, action in self.actions[direction].items():
            if action == "refuse" and self._found(name, text):
                return GuardrailDecision(False, None, name)
        if direction == "output":
            refused = self._claim(text)
            if refused:
                return GuardrailDecision(False, None, refused)
        cleaned, classes = self._redact(text, direction)
        return GuardrailDecision(True, cleaned, ",".join(classes))

    def _claim(self, line: str) -> str:
        """unapproved_claim:<id> for a known bad claim, unsupported_claim for a claim word with no approved text."""
        low = line.lower()
        for claim_id, text in self.claims.blocked:
            if text.lower() in low:
                return f"unapproved_claim:{claim_id}"
        if self._found("claim_word", line) and not any(c.exact_text.lower() in low for c in self.claims.approved):
            return "unsupported_claim"
        return ""


def message_for(reason: str) -> str:
    if reason.startswith("unapproved_claim"):
        return f"The reply used a claim that is not approved or out of date ({reason.split(':', 1)[1]}). It was stopped."
    if reason == "unsupported_claim":
        return "The reply made a product claim that is not in the approved claims. It was stopped."
    return MESSAGES.get(reason, "Blocked by the guardrails.")


def load_claims(path: str | None, today: date | None = None) -> Claims:
    if not path:
        return Claims()
    today = today or date.today()
    try:
        with open(path, encoding="utf-8") as f:
            brand = json.load(f)
        approved, blocked = [], []
        for product in brand.get("products", []):
            for claim in product.get("claims", []):
                start = date.fromisoformat(claim["valid_from"]) if claim.get("valid_from") else None
                end = date.fromisoformat(claim["valid_until"]) if claim.get("valid_until") else None
                valid = claim.get("approved") is True and start and end and start <= today <= end
                if valid:
                    approved.append(ApprovedClaim(claim["id"], claim["text"], claim.get("source") or "", start, end))
                else:
                    blocked.append((claim["id"], claim["text"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise GuardrailConfigError(f"cannot use brand file {path}: {exc}") from None
    return Claims(tuple(approved), tuple(blocked))


def load_guardrail(rules_file: str | None = None, brand_file: str | None = None, today: date | None = None) -> Guardrail:
    """Built-in rules, plus a JSON file {"patterns": {class: [regex]}, "actions": {"input"|"output": {class: action}}}."""
    patterns = {name: list(items) for name, items in PATTERNS.items()}
    actions = {direction: dict(items) for direction, items in ACTIONS.items()}
    if rules_file:
        try:
            with open(rules_file, encoding="utf-8") as f:
                extra = json.load(f)
            for name, items in extra.get("patterns", {}).items():
                if not isinstance(items, list) or not all(isinstance(p, str) for p in items):
                    raise ValueError(f"patterns.{name} must be a list of strings")
                for p in items:
                    re.compile(p)
                patterns.setdefault(name, []).extend(items)
            for direction, items in extra.get("actions", {}).items():
                if direction not in actions or not isinstance(items, dict):
                    raise ValueError(f"actions.{direction}: use input or output")
                for name, action in items.items():
                    PolicyAction(action)  # allow, redact or refuse
                    actions[direction][name] = action
        except (OSError, ValueError, AttributeError, re.error) as exc:
            raise GuardrailConfigError(f"cannot use guardrails file {rules_file}: {exc}") from None
    return Guardrail(patterns, actions, load_claims(brand_file, today))
