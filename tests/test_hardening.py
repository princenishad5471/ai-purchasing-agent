"""Tests for fail-closed data, idempotent review, and approval gating"""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.agent.tools import InvestigationTools, DataNotFoundError
from app.agent.orchestrator import PurchasingAgentOrchestrator, AlreadyReviewedError
from app.database import db


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", str(tmp_path / "test.db"))
    db.init_db()
    return db


def _recommendation(quantity=800, node="delhi-ncr-dark-store-a", product="coca-cola-500ml"):
    rec = {
        "recommendation_id": f"REC-{uuid.uuid4().hex[:8].upper()}",
        "product_id": product,
        "product_name": product,
        "node_id": node,
        "node_name": node,
        "recommended_quantity": quantity,
        "recommended_supplier": "supplier_x",
    }
    db.save_recommendation(rec)
    return rec["recommendation_id"]


def _po_count():
    with db.get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS n FROM purchase_orders")
        return cursor.fetchone()["n"]


def test_missing_data_raises_instead_of_defaulting():
    tools = InvestigationTools(data_dir="backend/data")
    with pytest.raises(DataNotFoundError):
        tools.get_current_inventory("typo-node", "coca-cola-500ml")
    with pytest.raises(DataNotFoundError):
        tools.get_demand_forecast("typo-node", "coca-cola-500ml")
    with pytest.raises(DataNotFoundError):
        tools.get_storage_capacity("typo-node", "coca-cola-500ml")
    with pytest.raises(DataNotFoundError):
        tools.get_budget_info("typo-node", "beverages")
    with pytest.raises(DataNotFoundError):
        tools.get_sales_velocity("typo-node", "coca-cola-500ml")


def test_unknown_node_review_creates_no_po(isolated_db):
    rec_id = _recommendation(node="typo-node")
    with pytest.raises(DataNotFoundError):
        PurchasingAgentOrchestrator().review_recommendation(rec_id)
    assert _po_count() == 0
    assert db.get_recommendation(rec_id)["status"] == "escalated"


def test_second_review_does_not_create_second_po(isolated_db):
    rec_id = _recommendation()
    agent = PurchasingAgentOrchestrator()

    result = agent.review_recommendation(rec_id)
    assert result["purchase_order"] is not None
    assert db.get_recommendation(rec_id)["status"] == "accepted"

    with pytest.raises(AlreadyReviewedError):
        agent.review_recommendation(rec_id)
    assert _po_count() == 1


def test_low_confidence_decision_is_escalated_not_executed(isolated_db):
    rec_id = _recommendation()
    agent = PurchasingAgentOrchestrator()
    original = agent.llm_client.make_decision
    agent.llm_client.make_decision = lambda rec, inv: {**original(rec, inv), "confidence": 0.3}

    result = agent.review_recommendation(rec_id)

    assert result["decision"].requires_approval is True
    assert result["purchase_order"] is None
    assert _po_count() == 0
    assert db.get_recommendation(rec_id)["status"] == "escalated"
    assert result["trace"][-1]["step"] == "escalated"


def test_committed_agent_spend_reduces_available_budget(isolated_db):
    # Store A has ₹180,000 remaining in static data; earlier agent POs used ₹179,000
    db.save_purchase_order({
        "po_id": "PO-PRIOR", "recommendation_id": "REC-PRIOR",
        "node_id": "delhi-ncr-dark-store-a", "supplier_id": "supplier_x",
        "supplier_name": "Supplier X", "line_items": [], "total_amount": 179000.0,
        "expected_delivery": "2099-01-01", "status": "submitted",
    })
    rec_id = _recommendation()

    result = PurchasingAgentOrchestrator().review_recommendation(rec_id)

    assert result["investigation"].budget.remaining == 1000.0
    assert result["constraint_validation"].validations["budget_available"].passed is False
    assert result["purchase_order"] is None
    assert _po_count() == 1  # only the prior PO


# ---- LLM client: untrusted output and failures fail closed ----

from types import SimpleNamespace
from app.agent.llm_client import LLMClient, default_model
from app.actions.purchase_order import PurchaseOrderManager
from app.models import SupplierInfo

REC = {"recommended_quantity": 800, "recommended_supplier": "supplier_x"}


def _anthropic_client(text=None, error=None, stop_reason="end_turn"):
    client = LLMClient(provider="anthropic")
    client.init_error = None

    def create(**kwargs):
        if error:
            raise error
        return SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type="text", text=text)],
        )

    client.anthropic_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client._build_prompt = lambda rec, inv: "prompt"
    return client


GOOD = '{"decision": "ACCEPT", "final_quantity": 800, "reasoning": "ok", "evidence": ["a"], "confidence": 0.9}'


def test_default_model_matches_provider():
    assert default_model("anthropic").startswith("claude-")
    assert LLMClient(provider="anthropic").model.startswith("claude-")


def test_llm_valid_json_including_code_fence_is_accepted():
    for text in (GOOD, f"```json\n{GOOD}\n```"):
        result = _anthropic_client(text)._anthropic_decision(REC, None)
        assert result["decision"] == "ACCEPT"
        assert result["final_quantity"] == 800
        assert result["llm_model"] == "claude-opus-5-5"


@pytest.mark.parametrize("bad", [
    "not json",
    '{"decision": "BUY_EVERYTHING", "final_quantity": 5, "reasoning": "", "evidence": [], "confidence": 0.9}',
    '{"decision": "ACCEPT", "final_quantity": -5, "reasoning": "", "evidence": [], "confidence": 0.9}',
    '{"decision": "ACCEPT", "final_quantity": 800, "reasoning": "", "evidence": [], "confidence": 7}',
    '{"decision": "ACCEPT", "reasoning": ""}',
])
def test_llm_invalid_output_is_escalated(bad):
    result = _anthropic_client(bad)._anthropic_decision(REC, None)
    assert result["decision"] == "INVESTIGATE_FURTHER"
    assert result["confidence"] == 0.0
    assert result["llm_model"] != "demo_mode"


def test_llm_api_error_or_early_stop_escalates_not_demo():
    result = _anthropic_client(error=RuntimeError("boom"))._anthropic_decision(REC, None)
    assert result["decision"] == "INVESTIGATE_FURTHER"
    assert "boom" in result["reasoning"]

    result = _anthropic_client(GOOD, stop_reason="max_tokens")._anthropic_decision(REC, None)
    assert result["decision"] == "INVESTIGATE_FURTHER"


def test_misconfigured_provider_escalates():
    client = LLMClient(provider="nonsense")
    result = client.make_decision(REC, None)
    assert result["decision"] == "INVESTIGATE_FURTHER"
    assert result["confidence"] == 0.0


# ---- PO retry and post-action validation ----

SUPPLIER = SupplierInfo(
    supplier_id="supplier_x", name="Supplier X", unit_price=18.5, moq=500,
    max_order_qty=5000, lead_time_days=2, available_quantity=5000, reliability_score=0.95,
)


def _create(manager, rec_id="REC-PO", max_retries=1):
    return manager.create_purchase_order(
        recommendation_id=rec_id, product_id="coca-cola-500ml", product_name="Coke",
        node_id="delhi-ncr-dark-store-a", supplier_info=SUPPLIER, quantity=800,
        max_retries=max_retries,
    )


def test_retry_after_partial_failure_reuses_same_po(isolated_db, monkeypatch):
    manager = PurchaseOrderManager()
    original = manager._validate_po_creation
    calls = {"n": 0}

    def flaky(po):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("validation backend down")
        return original(po)

    monkeypatch.setattr(manager, "_validate_po_creation", flaky)
    po, validation = _create(manager)

    assert po is not None and validation.escalated is False
    assert _po_count() == 1


def test_failed_post_check_escalates_and_frees_budget(isolated_db, monkeypatch):
    manager = PurchaseOrderManager()
    monkeypatch.setattr(manager, "_mock_notify_supplier", lambda po: False)
    po, validation = _create(manager)

    assert validation.escalated is True
    assert validation.failures == ["supplier_notified"]
    assert po.status.value == "failed"
    assert db.get_committed_spend("delhi-ncr-dark-store-a") == 0


def test_orchestrator_escalates_when_post_check_fails(isolated_db, monkeypatch):
    monkeypatch.setattr(PurchaseOrderManager, "_mock_notify_supplier", lambda self, po: False)
    rec_id = _recommendation()

    result = PurchasingAgentOrchestrator().review_recommendation(rec_id)

    steps = [t["step"] for t in result["trace"]]
    assert "po_created" not in steps
    assert "po_creation_failed_escalated" in steps
    assert db.get_recommendation(rec_id)["status"] == "escalated"
