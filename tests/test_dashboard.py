"""Tests for the Flask dashboard (dashboard/app.py)."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from dashboard.app import app


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _auth_header(user: str = "admin", password: str = "admin") -> dict:
    creds = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


# ---------- 20. test_dashboard_requires_auth ----------

def test_dashboard_requires_auth(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 401


# ---------- 21. test_dashboard_with_auth ----------

def test_dashboard_with_auth(client) -> None:
    resp = client.get("/", headers=_auth_header())
    assert resp.status_code == 200
    assert b"Solana Arb Bot" in resp.data


# ---------- 22. test_dashboard_api_stats_proxies ----------

def test_dashboard_api_stats_proxies(client) -> None:
    fake_health = {
        "status": "running",
        "uptime_sec": 300,
        "dry_run": True,
        "balance_sol": 1.5,
        "trades_total": 3,
        "profit_total": 0.0005,
        "opportunities_seen": 42,
        "errors_total": 0,
        "last_scan_sec_ago": 1.2,
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_health

    with patch("dashboard.app.httpx") as mock_httpx:
        mock_httpx.get.return_value = mock_resp
        resp = client.get("/api/stats", headers=_auth_header())

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "running"
    assert data["trades_total"] == 3


# ---------- 23. test_dashboard_ai_provider_get ----------

def test_dashboard_ai_provider_get(client) -> None:
    with patch("detector.nightly_report.ai_provider", "ollama"):
        resp = client.get("/api/ai-provider", headers=_auth_header())
    assert resp.status_code == 200
    data = resp.get_json()
    assert "ai_provider" in data


# ---------- 24. test_dashboard_ai_provider_set ----------

def test_dashboard_ai_provider_set(client) -> None:
    resp = client.post(
        "/api/ai-provider",
        headers=_auth_header(),
        json={"provider": "anthropic"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["ai_provider"] == "anthropic"


# ---------- 25. test_dashboard_ai_provider_invalid ----------

def test_dashboard_ai_provider_invalid(client) -> None:
    resp = client.post(
        "/api/ai-provider",
        headers=_auth_header(),
        json={"provider": "invalid_provider"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data
