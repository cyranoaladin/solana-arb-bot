"""Tests for nightly AI report module."""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from detector.nightly_report import generate_nightly_report, _call_ollama


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Ensure API keys and Ollama URL are controlled."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")


def test_generate_report_returns_none_for_missing_log():
    """Should return None when log file doesn't exist."""
    result = asyncio.get_event_loop().run_until_complete(
        generate_nightly_report(log_path="/tmp/this_log_does_not_exist_12345.log")
    )
    assert result is None


@pytest.mark.asyncio
async def test_ollama_success():
    """Mock Ollama API returning a valid report."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"response": "Rapport de test"}
    mock_resp.raise_for_status = MagicMock()

    with patch("detector.nightly_report.httpx.post", return_value=mock_resp):
        result = await _call_ollama("test prompt")
        assert result == "Rapport de test"


@pytest.mark.asyncio
async def test_ollama_fallback_to_none():
    """Ollama failure should return None (allows Anthropic fallback)."""
    import httpx
    with patch("detector.nightly_report.httpx.post", side_effect=httpx.HTTPError("connection refused")):
        result = await _call_ollama("test prompt")
        assert result is None


@pytest.mark.asyncio
async def test_generate_report_uses_ollama_first():
    """Should use Ollama and not call Anthropic when Ollama succeeds."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write('{"ts":"2026-03-24","level":"INFO","msg":"test"}\n')
        log_path = f.name

    with (
        patch("detector.nightly_report._call_ollama", new_callable=AsyncMock) as mock_ollama,
        patch("detector.nightly_report._call_anthropic", new_callable=AsyncMock) as mock_anthropic,
    ):
        mock_ollama.return_value = "Rapport Ollama"

        result = await generate_nightly_report(log_path=log_path)
        assert result == "Rapport Ollama"
        mock_ollama.assert_called_once()
        mock_anthropic.assert_not_called()

    import os
    os.unlink(log_path)
