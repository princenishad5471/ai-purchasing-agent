"""API security (auth, validation, errors) and the human approval workflow"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.main import app, orchestrator
from app.database import db

KEY = {"X-API-Key": "secret"}
BODY = {
    "product_id": "coca-cola-500ml", "product_name": "Coke",
    "node_id": "delhi-ncr-dark-store-a", "node_name": "A",
    "recommended_quantity": 800, "recommended_supplier": "supplier_x",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", str(tmp_path / "api.db"))
    db.init_db()
    monkeypatch.setenv("API_KEY", "secret")
    return TestClient(app)


def _force_decision(monkeypatch, **overrides):
    original = orchestrator.llm_client.make_decision
    monkeypatch.setattr(
        orchestrator.llm_client, "make_decision",
        lambda rec, inv: {**original(rec, inv), **overrides},
    )


def _escalated_rec(client, monkeypatch, quantity=800, **overrides):
    _force_decision(monkeypatch, **overrides)
    rec_id = client.post("/api/recommendations", json={**BODY, "recommended_quantity": quantity},
                         headers=KEY).json()["recommendation_id"]
    result = client.post(f"/api/recommendations/{rec_id}/review", headers=KEY)
    assert result.status_code == 200
    assert db.get_recommendation(rec_id)["status"] == "escalated"
    return rec_id


def _po_count():
    with db.get_cursor() as c:
        c.execute("SELECT COUNT(*) AS n FROM purchase_orders")
        return c.fetchone()["n"]


# ---- security ----

def test_writes_require_key_when_configured(client):
    assert client.post("/api/recommendations", json=BODY).status_code == 401
    assert client.post("/api/recommendations", json=BODY, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/api/recommendations", json=BODY, headers=KEY).status_code == 200
    assert client.get("/api/health").json()["auth_enabled"] is True


@pytest.mark.parametrize("patch", [
    {"recommended_quantity": 0}, {"recommended_quantity": -5},
    {"recommended_quantity": 10**9}, {"node_id": ""}, {"recommended_supplier": ""},
])
def test_invalid_input_rejected(client, patch):
    assert client.post("/api/recommendations", json={**BODY, **patch}, headers=KEY).status_code == 422


def test_approvals_disabled_without_api_key(client, monkeypatch):
    rec_id = _escalated_rec(client, monkeypatch, confidence=0.3)
    monkeypatch.delenv("API_KEY")
    r = client.post(f"/api/recommendations/{rec_id}/approve", json={"approved_by": "alice"})
    assert r.status_code == 503
    assert _po_count() == 0


def test_cors_does_not_allow_arbitrary_origin(client):
    r = client.options("/api/recommendations", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_server_errors_do_not_leak_details(client, monkeypatch):
    rec_id = client.post("/api/recommendations", json=BODY, headers=KEY).json()["recommendation_id"]
    monkeypatch.setattr(orchestrator, "_investigate", lambda rec: (_ for _ in ()).throw(RuntimeError("secret-internal-path")))
    r = client.post(f"/api/recommendations/{rec_id}/review", headers=KEY)
    assert r.status_code == 500
    assert "secret-internal-path" not in r.text


# ---- approval workflow ----

def test_approve_low_confidence_decision_creates_po(client, monkeypatch):
    rec_id = _escalated_rec(client, monkeypatch, confidence=0.3)
    assert _po_count() == 0

    r = client.post(f"/api/recommendations/{rec_id}/approve",
                    json={"approved_by": "alice", "notes": "checked with supplier"}, headers=KEY)

    assert r.status_code == 200
    assert r.json()["purchase_order"] is not None
    assert db.get_recommendation(rec_id)["status"] == "accepted"
    assert _po_count() == 1
    traces = {t["step"]: t["data"] for t in db.get_trace(rec_id)}
    assert traces["approved_by_human"]["approved_by"] == "alice"

    # can't approve twice
    again = client.post(f"/api/recommendations/{rec_id}/approve", json={"approved_by": "alice"}, headers=KEY)
    assert again.status_code == 409
    assert _po_count() == 1


def test_approval_cannot_override_hard_constraints(client, monkeypatch):
    # 3000 units: over the approval threshold AND over storage (1800)
    rec_id = _escalated_rec(client, monkeypatch, quantity=3000, decision="ACCEPT",
                            final_quantity=3000, confidence=0.95)

    r = client.post(f"/api/recommendations/{rec_id}/approve", json={"approved_by": "alice"}, headers=KEY)

    assert r.status_code == 409
    assert "storage" in r.json()["detail"]
    assert _po_count() == 0
    assert db.get_recommendation(rec_id)["status"] == "escalated"


def test_approve_requires_approver_name_and_valid_key(client, monkeypatch):
    rec_id = _escalated_rec(client, monkeypatch, confidence=0.3)
    assert client.post(f"/api/recommendations/{rec_id}/approve", json={}, headers=KEY).status_code == 422
    assert client.post(f"/api/recommendations/{rec_id}/approve", json={"approved_by": "a"},
                       headers={"X-API-Key": "wrong"}).status_code == 401
    assert _po_count() == 0


def test_cannot_approve_investigate_further(client, monkeypatch):
    rec_id = _escalated_rec(client, monkeypatch, decision="INVESTIGATE_FURTHER", confidence=0.6)
    r = client.post(f"/api/recommendations/{rec_id}/approve", json={"approved_by": "alice"}, headers=KEY)
    assert r.status_code == 409
    assert _po_count() == 0


def test_reject_closes_escalation_without_po(client, monkeypatch):
    rec_id = _escalated_rec(client, monkeypatch, confidence=0.3)

    r = client.post(f"/api/recommendations/{rec_id}/reject",
                    json={"rejected_by": "bob", "reason": "too much stock"}, headers=KEY)

    assert r.status_code == 200
    assert db.get_recommendation(rec_id)["status"] == "rejected"
    assert _po_count() == 0
    assert client.post(f"/api/recommendations/{rec_id}/approve",
                       json={"approved_by": "alice"}, headers=KEY).status_code == 409
