"""Deterministic synthetic field masking for synthetic demo data only."""

import hashlib
import re
from typing import Any

SENSITIVE = {
    "email",
    "phone",
    "telephone",
    "mobile",
    "name",
    "first_name",
    "last_name",
    "full_name",
    "address",
    "national_id",
    "ssn",
    "credit_card",
    "card_number",
}


def mask_record(record: dict[str, Any]) -> dict[str, Any]:
    """Replace common sensitive fields without mutating the source record."""
    # TODO: Integrate Gemma-assisted field classification with a reviewed privacy boundary.
    result = {}
    for key, value in record.items():
        normalized = re.sub(r"[ -]", "_", key.lower())
        if value is not None and normalized in SENSITIVE:
            digest = hashlib.sha256(str(value).encode()).hexdigest()[:12]
            result[key] = f"synthetic_{normalized}_{digest}"
        else:
            result[key] = value
    return result
