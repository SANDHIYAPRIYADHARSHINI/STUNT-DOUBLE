"""Synthetic sensitive-field masking."""

import pytest

from app.services.privacy_shield import mask_record


@pytest.mark.parametrize(
    "field", ["email", "phone", "name", "address", "national ID", "credit card"]
)
def test_mask_sensitive_fields(field):
    record = {field: "synthetic-input", "active": True}
    masked = mask_record(record)
    assert masked[field] != record[field]
    assert masked == mask_record(record)
    assert masked["active"] is True
    assert record[field] == "synthetic-input"


def test_null_remains_null():
    assert mask_record({"email": None}) == {"email": None}
