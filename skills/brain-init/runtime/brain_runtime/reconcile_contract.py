"""Canonical reconciliation contract.

Shared, deterministic vocabulary for capture-staged reconciliation records.
Python validates these contracts and their effects but never chooses a
semantic disposition — Claude and the curator do.
"""
import hashlib


ORIGINS = {"capture", "legacy"}
RECORD_STATUSES = {"staged", "pending_review", "complete", "incomplete"}
SEARCH_METHODS = {"qmd", "filesystem", "mixed", "unavailable"}
DISPOSITIONS = {
    "new", "corroborating", "updating",
    "contradicting", "superseding", "irrelevant",
}
CONFIDENCE_EFFECTS = {
    "increase", "decrease", "unchanged", "not_applicable",
}
REVIEW_STATES = {"not_required", "pending", "approved", "rejected"}
ACTION_STATES = {"pending", "applied", "not_applicable", "rejected"}
SENSITIVE_DISPOSITIONS = {"updating", "contradicting", "superseding"}


def normalize_claim_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("claim text must be a non-empty string")
    return " ".join(value.split())


def candidate_id(source_id: str, claim_text: str) -> str:
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source ID must be a non-empty string")
    payload = f"{source_id.strip()}\n{normalize_claim_text(claim_text)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"candidate-{digest[:12]}"
