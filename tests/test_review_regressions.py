"""Regression cases found by independent review, exercising behavior not source strings."""

from copy import deepcopy

from fastapi.testclient import TestClient

from commerceops.app import create_app
from commerceops.catalog import CART


def test_saved_diagnosis_restores_full_business_context(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "test.db"), base_url="http://127.0.0.1") as c:
        cart = deepcopy(CART)
        cart[0]["quantity"] = 2
        payload = {
            "question": "优惠为什么失效？",
            "is_new_customer": False,
            "at": "2026-11-01T00:00:00+08:00",
            "cart": cart,
        }
        d = c.post("/api/diagnoses", json=payload).json()
        saved = c.get("/api/diagnoses/" + d["id"]).json()
        assert saved.get("at") == payload["at"]
        assert saved.get("is_new_customer") is False
        assert saved.get("cart") == cart


def test_missing_collection_is_unknown_not_invalid_request(tmp_path):
    with TestClient(create_app(db_path=tmp_path / "test.db"), base_url="http://127.0.0.1") as c:
        cart = deepcopy(CART)
        cart[0]["collection"] = None
        r = c.post(
            "/api/diagnoses",
            json={"question": "可以使用哪些优惠？", "is_new_customer": True, "cart": cart},
        )
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "needs_info" and d["recommended_plan"] is None
        assert "cart[0].collection" in d["missing_fields"]
