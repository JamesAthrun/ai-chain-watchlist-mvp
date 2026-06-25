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


def free_chat(user_message: str, market_context: str = "") -> str:
    """Free-form chat with LLM, providing market context for informed answers.

    Returns LLM response or a fallback message if LLM is unavailable.
    """
    provider = get_llm_provider()

    if provider == "none" or provider == "":
        return "当前未配置 LLM，无法进行自由对话。请设置 LLM_PROVIDER。"

    system_prompt = (
        "你是一个专业的 AI 产业链盯盘助手，专注于美股 AI 半导体产业链投资分析。"
        "重要：本系统只关注美股（NASDAQ/NYSE），不涉及 A 股、港股或其他市场。"
        "所有标的均为美股，所有建议仅针对美股市场。"
        "你可以回答用户关于市场、个股、板块、交易策略等问题。"
        "回答要简洁专业，基于提供的实时市场数据。"
        "不要编造数据，如果没有相关信息就说明。"
        "这不是投资建议，仅供参考。"
    )

    user_msg = user_message
    if market_context:
        user_msg = f"当前市场数据:\n{market_context}\n\n用户问题: {user_message}"

    if provider == "deepseek":
        return _call_llm_chat("https://api.deepseek.com", os.getenv("DEEPSEEK_API_KEY", ""),
                              os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), system_prompt, user_msg)
    elif provider == "openai":
        return _call_llm_chat("https://api.openai.com", os.getenv("OPENAI_API_KEY", ""),
                              os.getenv("OPENAI_MODEL", "gpt-4o-mini"), system_prompt, user_msg)
    else:
        return "未知的 LLM 提供商，无法进行对话。"


def analyze_market(data_json: str, analysis_type: str = "market") -> Optional[str]:
    """Use LLM to analyze market data and provide actionable insights.

    analysis_type: "market" | "sleep_plan" | "portfolio"
    Returns analysis text, or None if LLM unavailable.
    """
    provider = get_llm_provider()
    if provider == "none" or provider == "":
        return None

    us_stock_constraint = (
        "重要约束：本系统只关注美股（NASDAQ/NYSE）AI 半导体产业链，不涉及 A 股、港股或其他市场。"
        "所有推荐标的必须是美股，禁止推荐任何 A 股或港股标的。\n\n"
    )

    system_prompts = {
        "market": (
            "你是一位专业的美股 AI 半导体产业链投资分析师。请基于以下实时行情数据，给出简洁的分析和操作建议。\n"
            "分析要求：\n"
            "1. 判断当前市场情绪（贪婪/恐惧/中性），说明依据\n"
            "2. 指出最强和最弱的板块，分析原因（产业链逻辑、事件驱动等）\n"
            "3. 对加仓候选给出优先级排序和理由\n"
            "4. 对避雷标的解释为什么要回避\n"
            "5. 给出今日核心操作建议（1-3条，具体到标的和方向）\n"
            "回答要简洁有力，每点不超过2句话。这不是投资建议，仅供参考。"
        ),
        "sleep_plan": (
            "你是一位专业的美股 AI 半导体产业链投资分析师。以下是系统根据规则计算出的睡觉挂单计划。\n"
            "请给出你的建议：\n"
            "1. 今晚的整体挂单策略（激进/保守/观望），说明理由\n"
            "2. 哪些标的值得挂单，哪些建议跳过\n"
            "3. 是否建议调整挂单折扣（比规则更保守或更激进）\n"
            "4. 需要注意的隔夜风险（如财报、宏观事件）\n"
            "回答要简洁实用，帮助用户快速决策。这不是投资建议，仅供参考。"
        ),
        "portfolio": (
            "你是一位专业的美股 AI 半导体产业链投资分析师。以下是用户当前的仓位数据。\n"
            "请给出仓位管理建议：\n"
            "1. 整体仓位健康度评估（集中度、暴露度、现金比例）\n"
            "2. 是否存在过度集中的风险，如何分散\n"
            "3. 基于当前市场状态，建议的仓位调整方向\n"
            "4. 具体的加减仓建议（标的+方向+理由）\n"
            "回答要简洁有力。这不是投资建议，仅供参考。"
        ),
    }

    system_prompt = us_stock_constraint + system_prompts.get(analysis_type, system_prompts["market"])
    user_msg = f"以下是当前数据:\n\n{data_json}\n\n请给出你的分析和建议（仅限美股）。"

    if provider == "deepseek":
        result = _call_llm_chat("https://api.deepseek.com", os.getenv("DEEPSEEK_API_KEY", ""),
                                os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), system_prompt, user_msg)
    elif provider == "openai":
        result = _call_llm_chat("https://api.openai.com", os.getenv("OPENAI_API_KEY", ""),
                                os.getenv("OPENAI_MODEL", "gpt-4o-mini"), system_prompt, user_msg)
    else:
        return None

    # If the call failed (error message), return None
    if result.startswith("API Key 未配置") or result.startswith("对话请求失败"):
        return None
    return result


def _call_llm_chat(base_url: str, api_key: str, model: str,
                    system_prompt: str, user_msg: str) -> str:
    """Generic LLM chat call."""
    if not api_key:
        return "API Key 未配置，无法进行对话。"

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
                "temperature": 0.7,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content if content else "LLM 返回为空。"
    except Exception as e:
        logger.warning(f"LLM chat call failed: {e}")
        return f"对话请求失败: {e}"
