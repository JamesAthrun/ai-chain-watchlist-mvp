"""Test cases for all API endpoints.

Run with: python -m pytest tests/ -v
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Use a temporary database for each test."""
    test_db = tmp_path / "test_portfolio.db"
    monkeypatch.setattr("app.core.database.DB_PATH", test_db)
    monkeypatch.setattr("app.core.database.DATA_DIR", tmp_path)

    # Initialize the DB
    from app.core.database import init_db
    init_db()

    yield test_db


@pytest.fixture
def client():
    """Create a test client."""
    from app.main import app
    return TestClient(app)


# ============================================================
# Health & Basic Endpoints
# ============================================================

class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "service" in data

    def test_root_endpoint(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"


# ============================================================
# Market Endpoints
# ============================================================

class TestMarket:
    def test_market_summary(self, client):
        resp = client.get("/api/market/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "market_regime" in data
        assert "benchmark_strength" in data
        assert "bucket_scores" in data
        assert "add_candidates" in data
        assert "do_not_buy" in data

    def test_market_summary_no_enhance(self, client):
        resp = client.get("/api/market/summary?enhance=false")
        assert resp.status_code == 200
        data = resp.json()
        assert "llm_analysis" not in data

    def test_watchlist(self, client):
        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        data = resp.json()
        assert "buckets" in data

    def test_sleep_plan(self, client):
        resp = client.get("/api/sleep-plan")
        assert resp.status_code == 200
        data = resp.json()
        assert "orders" in data
        assert "market_regime" in data
        assert "total_pending_amount" in data

    def test_sleep_plan_no_enhance(self, client):
        resp = client.get("/api/sleep-plan?enhance=false")
        assert resp.status_code == 200
        data = resp.json()
        assert "llm_analysis" not in data

    def test_refresh(self, client):
        resp = client.post("/api/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "refreshed_at" in data


# ============================================================
# Portfolio Endpoints
# ============================================================

class TestPortfolio:
    def test_get_portfolio_initial(self, client):
        """Initial portfolio should have cash from portfolio.json seed."""
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert "account_value" in data
        assert "cash" in data
        assert "positions" in data
        assert "cash_pct" in data
        assert data["cash"] == 40000.0
        assert data["positions"] == []

    def test_get_portfolio_no_enhance(self, client):
        resp = client.get("/api/portfolio?enhance=false")
        assert resp.status_code == 200
        assert "llm_analysis" not in resp.json()

    def test_trade_buy(self, client):
        """Buy trade should reduce cash and add position."""
        resp = client.post("/api/portfolio/trade", json={
            "ticker": "NVDA",
            "action": "buy",
            "shares": 100,
            "price": 135.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["cash_before"] == 40000.0
        assert data["cash_after"] == 26500.0
        assert data["position"]["shares_after"] == 100.0
        assert data["position"]["avg_cost"] == 135.0

    def test_trade_buy_updates_portfolio(self, client):
        """After buy, portfolio should reflect the new position."""
        client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "buy", "shares": 50, "price": 130.0,
        })
        resp = client.get("/api/portfolio")
        data = resp.json()
        assert data["cash"] == 40000.0 - 6500.0
        assert len(data["positions"]) == 1
        assert data["positions"][0]["ticker"] == "NVDA"
        assert data["positions"][0]["shares"] == 50.0

    def test_trade_buy_average_cost(self, client):
        """Multiple buys should average cost correctly."""
        client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "buy", "shares": 100, "price": 130.0,
        })
        resp = client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "buy", "shares": 100, "price": 140.0,
        })
        data = resp.json()
        assert data["position"]["shares_after"] == 200.0
        assert data["position"]["avg_cost"] == 135.0  # (13000+14000)/200

    def test_trade_sell(self, client):
        """Sell should increase cash and reduce position."""
        client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "buy", "shares": 100, "price": 130.0,
        })
        resp = client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "sell", "shares": 50, "price": 150.0,
        })
        data = resp.json()
        assert data["status"] == "ok"
        assert data["position"]["shares_after"] == 50.0
        assert data["cash_after"] == 40000.0 - 13000.0 + 7500.0

    def test_trade_sell_all(self, client):
        """Selling all shares should remove position."""
        client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "buy", "shares": 100, "price": 130.0,
        })
        client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "sell", "shares": 100, "price": 150.0,
        })
        resp = client.get("/api/portfolio")
        assert resp.json()["positions"] == []

    def test_trade_sell_no_position(self, client):
        """Selling without position should error."""
        resp = client.post("/api/portfolio/trade", json={
            "ticker": "AAPL", "action": "sell", "shares": 50, "price": 100.0,
        })
        data = resp.json()
        assert data["status"] == "error"

    def test_trade_invalid_action(self, client):
        """Invalid action should error."""
        resp = client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "short", "shares": 50, "price": 100.0,
        })
        data = resp.json()
        assert data["status"] == "error"

    def test_put_portfolio(self, client):
        """PUT should replace entire portfolio."""
        resp = client.put("/api/portfolio", json={
            "account_value": 50000,
            "cash": 20000,
            "positions": [
                {"ticker": "NVDA", "shares": 100, "avg_cost": 130},
                {"ticker": "AVGO", "shares": 50, "avg_cost": 180},
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify
        portfolio = client.get("/api/portfolio").json()
        assert portfolio["cash"] == 20000.0
        assert len(portfolio["positions"]) == 2

    def test_trade_history(self, client):
        """Trade history should record all operations."""
        client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "buy", "shares": 100, "price": 135.0,
        })
        client.post("/api/portfolio/trade", json={
            "ticker": "AVGO", "action": "buy", "shares": 50, "price": 180.0,
        })

        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 200
        data = resp.json()
        # seed + 2 trades = 3 entries
        assert data["count"] >= 2
        # Most recent first
        assert data["trades"][0]["ticker"] == "AVGO"
        assert data["trades"][1]["ticker"] == "NVDA"

    def test_trade_history_filter_by_ticker(self, client):
        """History can be filtered by ticker."""
        client.post("/api/portfolio/trade", json={
            "ticker": "NVDA", "action": "buy", "shares": 100, "price": 135.0,
        })
        client.post("/api/portfolio/trade", json={
            "ticker": "AVGO", "action": "buy", "shares": 50, "price": 180.0,
        })

        resp = client.get("/api/portfolio/history?ticker=NVDA")
        data = resp.json()
        assert all(t["ticker"] == "NVDA" for t in data["trades"])


# ============================================================
# Chat Endpoint
# ============================================================

class TestChat:
    def test_chat_sleep_plan_intent(self, client):
        """Chat should recognize sleep plan keywords."""
        resp = client.post("/api/chat", json={"message": "睡前挂单计划"})
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "market_regime" in data

    def test_chat_avoid_intent(self, client):
        """Chat should recognize avoid keywords."""
        resp = client.post("/api/chat", json={"message": "不能接的标的"})
        assert resp.status_code == 200
        assert "answer" in resp.json()

    def test_chat_add_candidate_intent(self, client):
        """Chat should recognize add candidate keywords."""
        resp = client.post("/api/chat", json={"message": "能加仓的有哪些"})
        assert resp.status_code == 200
        assert "answer" in resp.json()

    def test_chat_strong_bucket_intent(self, client):
        """Chat should recognize strong bucket keywords."""
        resp = client.post("/api/chat", json={"message": "哪个板块强"})
        assert resp.status_code == 200
        assert "answer" in resp.json()

    def test_chat_report_intent(self, client):
        """Chat should recognize report keywords."""
        resp = client.post("/api/chat", json={"message": "盯盘报告"})
        assert resp.status_code == 200
        assert "answer" in resp.json()

    def test_chat_empty_message(self, client):
        """Empty message should still return a response."""
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 200


# ============================================================
# Portfolio Parse/Confirm (Natural Language)
# ============================================================

class TestPortfolioNatural:
    def test_parse_returns_preview(self, client):
        """Parse should return structured data + preview when LLM works."""
        # Mock LLM to return a known response
        mock_parsed = {"type": "trade", "trades": [{"action": "buy", "ticker": "NVDA", "shares": 100, "price": 135}]}
        with patch("app.api.routes_portfolio.parse_trade_intent", return_value=mock_parsed):
            resp = client.post("/api/portfolio/parse", json={"text": "买了100股NVDA 均价135"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["parsed"]["type"] == "trade"
            assert "preview" in data

    def test_parse_failure(self, client):
        """Parse should return error when LLM can't parse."""
        with patch("app.api.routes_portfolio.parse_trade_intent", return_value=None):
            resp = client.post("/api/portfolio/parse", json={"text": "hello"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "error"

    def test_confirm_trade(self, client):
        """Confirm should execute the parsed trade."""
        parsed = {"type": "trade", "trades": [{"action": "buy", "ticker": "MRVL", "shares": 200, "price": 80}]}
        resp = client.post("/api/portfolio/confirm", json={"parsed": parsed})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        # Verify position exists
        portfolio = client.get("/api/portfolio").json()
        tickers = [p["ticker"] for p in portfolio["positions"]]
        assert "MRVL" in tickers

    def test_confirm_set_portfolio(self, client):
        """Confirm set_portfolio should replace all positions."""
        parsed = {
            "type": "set_portfolio",
            "account_value": 60000,
            "cash": 30000,
            "positions": [
                {"ticker": "NVDA", "shares": 100, "avg_cost": 150},
                {"ticker": "AVGO", "shares": 50, "avg_cost": 200},
            ],
        }
        resp = client.post("/api/portfolio/confirm", json={"parsed": parsed})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        portfolio = client.get("/api/portfolio").json()
        assert portfolio["cash"] == 30000.0
        assert len(portfolio["positions"]) == 2

    def test_confirm_invalid_type(self, client):
        """Confirm with unknown type should error."""
        resp = client.post("/api/portfolio/confirm", json={"parsed": {"type": "unknown"}})
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
