"""Optional LLM client for report enhancement."""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def get_llm_provider() -> str:
    return os.getenv("LLM_PROVIDER", "none").lower()


def enhance_report(
    template_report: str,
    market_summary_json: str = "",
    portfolio_summary_json: str = "",
    rules_json: str = "",
) -> str:
    """Enhance the template report using LLM if configured.

    If LLM is not configured or fails, returns the template report as-is.
    The LLM only polishes the language; it cannot override risk rules.
    """
    provider = get_llm_provider()

    if provider == "none" or provider == "":
        return template_report

    if provider == "deepseek":
        return _call_deepseek(template_report, market_summary_json)
    elif provider == "openai":
        return _call_openai(template_report, market_summary_json)
    else:
        logger.warning(f"Unknown LLM provider: {provider}, returning template report")
        return template_report


def _call_deepseek(template_report: str, context: str) -> str:
    """Call DeepSeek API (OpenAI-compatible)."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        logger.info("DEEPSEEK_API_KEY not set, returning template report")
        return template_report

    base_url = "https://api.deepseek.com"
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    system_prompt = (
        "你是一个 AI 产业链盯盘助手。请把以下结构化报告润色成自然、简洁的中文。"
        "不要改变任何数据和结论，不要添加新的交易建议，不要绕过风控规则。"
        "保持专业但易读。"
    )

    user_msg = f"请润色以下报告:\n\n{template_report}"

    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 2000,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            return content
        return template_report
    except Exception as e:
        logger.warning(f"DeepSeek API call failed: {e}")
        return template_report


def _call_openai(template_report: str, context: str) -> str:
    """Call OpenAI API."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.info("OPENAI_API_KEY not set, returning template report")
        return template_report

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    system_prompt = (
        "你是一个 AI 产业链盯盘助手。请把以下结构化报告润色成自然、简洁的中文。"
        "不要改变任何数据和结论，不要添加新的交易建议，不要绕过风控规则。"
        "保持专业但易读。"
    )

    user_msg = f"请润色以下报告:\n\n{template_report}"

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 2000,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            return content
        return template_report
    except Exception as e:
        logger.warning(f"OpenAI API call failed: {e}")
        return template_report
