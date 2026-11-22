from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.nexora_workspace.creator_workflow import (
    _merchant_payment_matches, _payment_expired, _receipt_in_use,
)


def test_payment_expiry_is_persisted_policy_not_only_checkout_ui() -> None:
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert _payment_expired({"expires_at": future}) is False
    assert _payment_expired({"expires_at": past}) is True


def test_legacy_payment_uses_created_at_plus_24_hours() -> None:
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert _payment_expired({"created_at": recent}) is False
    assert _payment_expired({"created_at": old}) is True


def test_missing_or_invalid_expiry_fails_closed() -> None:
    assert _payment_expired({}) is True
    assert _payment_expired({"expires_at": "not-a-date"}) is True
    assert _payment_expired({"created_at": "not-a-date"}) is True


def test_receipt_code_cannot_be_reused_by_another_local_payment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEXORA_DATABASE_URL", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("NEXORA_ENV", raising=False)
    manager = SimpleNamespace(root=tmp_path / "projects")
    commerce = manager.root.parent / "nexora-commerce"
    commerce.mkdir(parents=True)
    (commerce / "payments.json").write_text(
        json.dumps({"payments": [
            {"payment_id": "payment-1", "receipt_code": "QWE123456"}
        ]}),
        encoding="utf-8",
    )
    assert _receipt_in_use(manager, "qwe123456", "payment-2") is True
    assert _receipt_in_use(manager, "qwe123456", "payment-1") is False



def test_merchant_receipt_must_exactly_match_customer_claim_and_invoice() -> None:
    record = {
        "status": "claimed",
        "receipt_code": "QWE123456",
        "paid_amount_kes": 499,
        "amount_kes": 499,
    }
    assert _merchant_payment_matches(record, "qwe123456", 499) is True
    assert _merchant_payment_matches(record, "QWE123457", 499) is False
    assert _merchant_payment_matches(record, "QWE123456", 500) is False


def test_merchant_receipt_cannot_verify_an_unclaimed_or_expired_style_record() -> None:
    record = {
        "status": "pending",
        "receipt_code": "QWE123456",
        "paid_amount_kes": 499,
        "amount_kes": 499,
    }
    assert _merchant_payment_matches(record, "QWE123456", 499) is False
