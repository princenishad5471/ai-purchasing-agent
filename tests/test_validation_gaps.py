"""Category budget, storage/allocation, open-PO handling, edge cases, trace order"""
import json
import os
import shutil
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.agent.tools import InvestigationTools, DataNotFoundError
from app.agent.orchestrator import PurchasingAgentOrchestrator
from app.database import db, Database

NODE, PRODUCT = "delhi-ncr-dark-store-a", "coca-cola-500ml"


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", str(tmp_path / "gaps.db"))
    db.init_db()
    return db


@pytest.fixture
def data_dir(tmp_path):
    dest = tmp_path / "data"
    shutil.copytree("backend/data", dest)
    return dest


def _rec(quantity=800):
    rec = {"recommendation_id": f"REC-{uuid.uuid4().hex[:8].upper()}", "product_id": PRODUCT,
           "product_name": "Coke", "node_id": NODE, "node_name": "A",
           "recommended_quantity": quantity, "recommended_supplier": "supplier_x"}
    db.save_recommendation(rec)
    return rec["recommendation_id"]


def _prior_po(quantity, amount, status="submitted", delivery="2099-01-01"):
    db.save_purchase_order({
        "po_id": f"PO-{uuid.uuid4().hex[:6]}", "recommendation_id": "REC-PRIOR", "node_id": NODE,
        "supplier_id": "supplier_x", "supplier_name": "X", "total_amount": amount,
        "expected_delivery": delivery, "status": status,
        "line_items": [{"product_id": PRODUCT, "product_name": "Coke", "quantity": quantity,
                        "unit_price": amount / quantity, "total_price": amount}],
    })


def _agent_with_decision(monkeypatch, **overrides):
    agent = PurchasingAgentOrchestrator()
    original = agent.llm_client.make_decision
    monkeypatch.setattr(agent.llm_client, "make_decision",
                        lambda rec, inv: {**original(rec, inv), **overrides})
    return agent


# ---- open POs ----

def test_cancelled_and_delivered_open_pos_are_ignored(data_dir):
    path = data_dir / "open_pos.json"
    data = json.loads(path.read_text())
    data[NODE][0]["status"] = "cancelled"
    path.write_text(json.dumps(data))
    assert InvestigationTools(data_dir=str(data_dir)).get_open_purchase_orders(NODE, PRODUCT) == []


def test_overdue_active_po_counts_toward_coverage():
    tools = InvestigationTools(data_dir="backend/data")
    orders = tools.get_open_purchase_orders(NODE, PRODUCT)  # delivery date is in the past
    with_po = tools.calculate_inventory_coverage(120, 30, 85, orders)
    without = tools.calculate_inventory_coverage(120, 30, 85, [])
    assert with_po > without


def test_invalid_delivery_date_fails_instead_of_being_swallowed(data_dir):
    path = data_dir / "open_pos.json"
    data = json.loads(path.read_text())
    data[NODE][0]["expected_delivery"] = "next tuesday"
    path.write_text(json.dumps(data))
    tools = InvestigationTools(data_dir=str(data_dir))
    with pytest.raises(DataNotFoundError):
        tools.calculate_inventory_coverage(120, 30, 85, tools.get_open_purchase_orders(NODE, PRODUCT))


# ---- storage / allocation ----

def test_storage_is_net_of_inbound_stock(isolated_db):
    agent = PurchasingAgentOrchestrator()
    inv = agent._investigate(db.get_recommendation(_rec()))
    assert inv.storage.available == 1800 - 500  # open PO of 500 is on its way

    _prior_po(quantity=300, amount=5550)
    inv = agent._investigate(db.get_recommendation(_rec()))
    assert inv.storage.available == 1800 - 500 - 300  # plus agent PO in flight


def test_quantity_over_product_allocation_is_escalated(isolated_db, monkeypatch):
    # 1000 fits storage (1300 free) but exceeds the 800-unit allocation for this product
    agent = _agent_with_decision(monkeypatch, decision="ACCEPT", final_quantity=1000, confidence=0.9)
    result = agent.review_recommendation(_rec(1000))

    assert result["constraint_validation"].validations["product_allocation"].passed is False
    assert result["purchase_order"] is None


def test_demo_modify_respects_allocation_and_storage(isolated_db):
    from app.agent.llm_client import LLMClient
    agent = PurchasingAgentOrchestrator()
    inv = agent._investigate({"recommendation_id": "R", "product_id": PRODUCT, "node_id": NODE,
                              "recommended_supplier": "supplier_x"})
    result = LLMClient("demo")._demo_decision(
        {"recommended_quantity": 1000, "recommended_supplier": "supplier_x"}, inv)
    assert result["decision"] == "MODIFY" and result["final_quantity"] == 800


def test_demo_escalates_instead_of_modifying_to_zero_when_storage_is_full(isolated_db):
    from app.agent.llm_client import LLMClient
    _prior_po(quantity=1300, amount=24050)  # fills the remaining 1300 units of space
    inv = PurchasingAgentOrchestrator()._investigate(
        {"recommendation_id": "R", "product_id": PRODUCT, "node_id": NODE,
         "recommended_supplier": "supplier_x"})
    assert inv.storage.available == 0
    result = LLMClient("demo")._demo_decision(
        {"recommended_quantity": 800, "recommended_supplier": "supplier_x"}, inv)
    assert result["decision"] == "INVESTIGATE_FURTHER"
    assert result["final_quantity"] == 800


# ---- category budget ----

def test_category_budget_is_enforced_net_of_committed_spend(isolated_db):
    # Beverages budget at store A is 50,000; 40,000 already committed leaves 10,000 < 14,800
    _prior_po(quantity=2000, amount=40000, delivery="2000-01-01")  # delivered: spend counts, space doesn't
    result = PurchasingAgentOrchestrator().review_recommendation(_rec())

    checks = result["constraint_validation"].validations
    assert checks["category_budget"].passed is False
    assert checks["budget_available"].passed is True  # node budget alone would have allowed it
    assert result["purchase_order"] is None


def test_category_budget_passes_when_within_limit(isolated_db):
    result = PurchasingAgentOrchestrator().review_recommendation(_rec())
    assert result["constraint_validation"].validations["category_budget"].passed is True
    assert result["purchase_order"] is not None


# ---- edge cases ----

def test_zero_demand_does_not_crash(isolated_db):
    agent = PurchasingAgentOrchestrator()
    agent.tools.demand_data[NODE][PRODUCT]["daily_avg"] = 0
    result = agent.review_recommendation(_rec())  # previously ZeroDivisionError -> HTTP 500
    assert result["decision"] is not None


# ---- audit trail ----

def test_trace_is_returned_in_insertion_order(isolated_db):
    rec_id = _rec()
    steps = [f"step_{i:02d}" for i in range(30)]
    for step in steps:
        db.add_trace(rec_id, step, {})  # many writes inside the same second
    assert [t["step"] for t in db.get_trace(rec_id)] == steps


def test_database_path_comes_from_env_not_cwd(tmp_path, monkeypatch):
    target = str(tmp_path / "custom.db")
    monkeypatch.setenv("DATABASE_PATH", target)
    assert Database().db_path == target
    assert os.path.exists(target)
