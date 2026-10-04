"""Contract tests use the real service, SQLite and lexical retriever."""

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PAYLOAD = {
    "question": "P2 为什么没有九折，NEW30 为什么不能叠加？",
    "is_new_customer": True,
    "at": "2026-10-03T12:00:00+08:00",
}


def make_app(tmp_path, **kwargs):
    assert (Path(__file__).parents[1] / "commerceops/app.py").exists(), (
        "Product API not implemented"
    )
    return importlib.import_module("commerceops.app").create_app(
        db_path=tmp_path / "app.sqlite3", **kwargs
    )


@pytest.fixture
def client(tmp_path):
    with TestClient(make_app(tmp_path), base_url="http://127.0.0.1") as c:
        yield c


def test_complete_diagnosis_and_real_evidence(client):
    response = client.post("/api/diagnoses", json=PAYLOAD)
    assert response.status_code == 200
    d = response.json()
    assert d["status"] == "resolved"
    assert d["backend"] == "lexical-demo"
    assert d["recommended_plan"] == "D2"
    plans = {p["id"]: p for p in d["plans"]}
    assert plans["D1"]["total"] == "375.00"
    assert plans["D2"]["total"] == "370.00"
    assert not plans.get("D1+D2", {}).get("eligible", False)
    assert {"R1", "R2", "R3", "R4"} <= {e["id"] for e in d["evidence"]}
    assert all(e["content"] and e["version"] == "demo-v3" for e in d["evidence"])
    assert "370.00" in d["answer"]
    assert client.get(f"/api/diagnoses/{d['id']}").json()["answer"] == d["answer"]


def test_clarification_resumes_original_cart(client):
    p = dict(PAYLOAD, is_new_customer=None)
    d = client.post("/api/diagnoses", json=p).json()
    assert d["status"] == "needs_info"
    assert "is_new_customer" in d["missing_fields"]
    assert d["recommended_plan"] is None
    newer = client.post(f"/api/diagnoses/{d['id']}/continue", json={"is_new_customer": True}).json()
    assert newer["status"] == "resolved"
    assert newer["recommended_plan"] == "D2"
    assert newer["parent_id"] == d["id"]


def test_feedback_and_history_survive_reopen(tmp_path):
    with TestClient(make_app(tmp_path), base_url="http://127.0.0.1") as c:
        d = c.post("/api/diagnoses", json=PAYLOAD).json()
        r = c.post(
            f"/api/diagnoses/{d['id']}/feedback", json={"rating": "helpful", "comment": "证据明确"}
        )
        assert r.status_code == 200 and r.json()["saved"]
    with TestClient(make_app(tmp_path), base_url="http://127.0.0.1") as c:
        assert c.get("/api/diagnoses").json()["items"][0]["id"] == d["id"]
        assert c.get(f"/api/diagnoses/{d['id']}").json()["feedback"][0]["rating"] == "helpful"


def test_no_evidence_no_conclusion(tmp_path):
    class EmptyRetriever:
        backend = "empty-test"

        async def search(self, query, mode="mix", limit=6):
            return []

    with TestClient(
        make_app(tmp_path, retriever=EmptyRetriever()), base_url="http://127.0.0.1"
    ) as c:
        d = c.post("/api/diagnoses", json=PAYLOAD).json()
        assert d["status"] == "insufficient_evidence"
        assert d["recommended_plan"] is None
        assert d["plans"] == [] and d["checks"] == []


def test_retrieval_failure_does_not_masquerade_as_success(tmp_path):
    class FailedRetriever:
        backend = "lightrag"

        async def search(self, query, mode="mix", limit=6):
            raise RuntimeError("secret-api-token")

    with TestClient(
        make_app(tmp_path, retriever=FailedRetriever()), base_url="http://127.0.0.1"
    ) as c:
        r = c.post("/api/diagnoses", json=PAYLOAD)
        assert r.json()["status"] == "insufficient_evidence"
        assert r.json()["backend"] == "lightrag"
        assert "secret-api-token" not in r.text


@pytest.mark.parametrize(
    "patch",
    [
        {"question": ""},
        {"question": "x" * 1001},
        {"at": "2026-10-03T12:00:00"},
        {"is_new_customer": "true"},
        {"tenant_id": "foreign"},
        {"cart": []},
    ],
)
def test_invalid_input_rejected(client, patch):
    assert client.post("/api/diagnoses", json=dict(PAYLOAD, **patch)).status_code == 422


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1.00"])
def test_invalid_price_rejected(client, bad):
    cart = client.get("/api/catalog").json()["cart"]
    cart[0]["price"] = bad
    assert client.post("/api/diagnoses", json=dict(PAYLOAD, cart=cart)).status_code == 422


def test_unknown_topic_has_no_made_up_diagnosis(client):
    d = client.post("/api/diagnoses", json=dict(PAYLOAD, question="今天北京的天气怎么样？")).json()
    assert d["status"] == "unsupported"
    assert not d["plans"]


def test_end_time_is_expired(client):
    d = client.post("/api/diagnoses", json=dict(PAYLOAD, at="2026-11-01T00:00:00+08:00")).json()
    assert d["status"] == "resolved"
    assert d["recommended_plan"] is None
    assert any(c["rule_id"] == "R4" and c["result"] == "fail" for c in d["checks"])


def test_cross_origin_write_and_foreign_host_rejected(client):
    assert (
        client.post(
            "/api/diagnoses", json=PAYLOAD, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/diagnoses", json=PAYLOAD, headers={"Origin": "http://127.0.0.1"}
        ).status_code
        == 200
    )
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_missing_id_and_invalid_feedback(client):
    assert client.get("/api/diagnoses/missing").status_code == 404
    assert (
        client.post("/api/diagnoses/missing/feedback", json={"rating": "helpful"}).status_code
        == 404
    )
    d = client.post("/api/diagnoses", json=PAYLOAD).json()
    assert (
        client.post(f"/api/diagnoses/{d['id']}/feedback", json={"rating": "whatever"}).status_code
        == 422
    )
