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
