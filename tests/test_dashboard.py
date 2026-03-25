"""Tests for the Flask dashboard (dashboard/app.py)."""

from __future__ import annotations

import base64
import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Set strong test credentials BEFORE importing the app
os.environ["DASHBOARD_USER"] = "testuser"
os.environ["DASHBOARD_PASS"] = "testpass_strong_42!"
os.environ["TESTING"] = "true"

from dashboard.app import app


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _auth_header(user: str = "testuser", password: str = "testpass_strong_42!") -> dict:
    creds = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def test_dashboard_requires_auth(client) -> None:
    resp = client.get("/")
    assert resp.status_code == 401


def test_dashboard_with_auth(client) -> None:
    resp = client.get("/", headers=_auth_header())
    assert resp.status_code == 200
    assert b"Solana Arb Bot" in resp.data


def test_dashboard_api_stats_proxies(client) -> None:
    fake_health = {"status": "running", "trades_total": 3}
    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_health

    with patch("dashboard.app.httpx") as mock_httpx:
        mock_httpx.get.return_value = mock_resp
        resp = client.get("/api/stats", headers=_auth_header())

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "running"


def test_dashboard_ai_provider_get(client) -> None:
    with patch("detector.nightly_report.ai_provider", "ollama"):
        resp = client.get("/api/ai-provider", headers=_auth_header())
    assert resp.status_code == 200
    data = resp.get_json()
    assert "ai_provider" in data


def test_dashboard_ai_provider_set(client) -> None:
    resp = client.post(
        "/api/ai-provider",
        headers=_auth_header(),
        json={"provider": "anthropic"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True


def test_dashboard_ai_provider_invalid(client) -> None:
    resp = client.post(
        "/api/ai-provider",
        headers=_auth_header(),
        json={"provider": "invalid_provider"},
    )
    assert resp.status_code == 400


def test_dashboard_rejects_wrong_auth(client) -> None:
    resp = client.get("/", headers=_auth_header("wrong", "wrong"))
    assert resp.status_code == 401
