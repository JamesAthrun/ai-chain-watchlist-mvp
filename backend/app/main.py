"""FastAPI application entry point."""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from app.api.routes_chat import router as chat_router
from app.api.routes_market import router as market_router
from app.api.routes_portfolio import router as portfolio_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="AI 产业链盯盘助手 MVP",
    description="个人 AI 产业链盯盘助手，跟踪半导体/AI 产业链行情",
    version="0.1.0",
)

# Register routers
app.include_router(market_router)
app.include_router(portfolio_router)
app.include_router(chat_router)


@app.get("/")
async def root():
    return {
        "service": "ai-chain-watchlist-mvp",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
    }
