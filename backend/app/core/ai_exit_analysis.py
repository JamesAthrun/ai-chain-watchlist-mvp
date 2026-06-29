"""AI-enhanced exit analysis — DeepSeek explanation layer over deterministic exit-plan.

Consumes the structured output of exit_engine.generate_exit_plan(), runs deterministic
pre-checks (exposure, concentration, conflicts), then calls DeepSeek to produce
plain-English explanations and risk audit. Falls back to deterministic output if
DeepSeek fails or is unavailable.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# --------------- Static user profile (no auth system) ---------------

USER_PROFILE = {
    "strategy": "LONG_TERM_LOW_BUY",
    "preferCorePositions": True,
    "maxTotalExposurePct": 75,
    "maxSingleCorePct": 15,
    "maxSingleSemiCorePct": 10,
    "maxSingleHighBetaPct": 5,
    "maxSingleLeveragedPct": 3,
    "timezone": "Asia/Singapore",
}

# Exposure thresholds per position type
_MAX_SINGLE_EXPOSURE = {
    "CORE": 15,
    "SEMI_CORE": 10,
    "CYCLICAL": 12,
    "HIGH_BETA": 5,
    "LEVERAGED_ETF": 3,
}

_SECTOR_CONCENTRATION_THRESHOLD = 35  # percent


# --------------- Deterministic Pre-Checks ---------------

def compute_exit_prechecks(
    portfolio_summary: dict,
    exit_plan: dict,
    daily_plan: Optional[dict] = None,
    global_brief: Optional[dict] = None,
) -> dict:
    """Run deterministic pre-checks before calling DeepSeek.

    Returns structured pre-check results for both the prompt and fallback.
    """
    position_pct = portfolio_summary.get("position_pct", 0)
    elevated_exposure = position_pct >= 65
    high_risk_exposure = position_pct >= 75

    # Sector concentration
    bucket_exposure = portfolio_summary.get("bucket_exposure", {})
    concentrated_sectors = [
        {"sectorGroup": k, "exposurePct": round(v, 1)}
        for k, v in bucket_exposure.items()
        if v >= _SECTOR_CONCENTRATION_THRESHOLD
    ]

    # Buy vs Exit conflicts
    buy_exit_conflicts = []
    if daily_plan:
        buy_symbols = set()
        orders = daily_plan.get("orders", [])
        for order in orders:
            ticker = order.get("ticker") or order.get("symbol", "")
            if ticker:
                buy_symbols.add(ticker)

        exit_plans = exit_plan.get("exitPlans", [])
        for plan in exit_plans:
            ticker = plan.get("ticker", "")
            action = plan.get("action", "HOLD")
            if ticker in buy_symbols and action in ("TRIM_PROFIT", "TRIM_RISK", "REDUCE_1_3", "REDUCE_1_2", "REDUCE_2_3", "EXIT"):
                buy_exit_conflicts.append({
                    "symbol": ticker,
                    "dailyPlanAction": "BUY",
                    "exitPlanAction": action,
                })

    # High-beta risk conflicts
    high_beta_conflicts = []
    if global_brief:
        adjustment = global_brief.get("dailyPlanAdjustment", {})
        allow_high_beta = adjustment.get("allowHighBeta", True)
        if not allow_high_beta:
            exit_plans = exit_plan.get("exitPlans", [])
            high_beta_conflicts = [
                p["ticker"] for p in exit_plans if p.get("type") == "HIGH_BETA"
            ]

    # Leveraged ETF conflicts (always flagged)
    leveraged_conflicts = [
        p["ticker"] for p in exit_plan.get("exitPlans", [])
        if p.get("type") == "LEVERAGED_ETF"
    ]

    # Single-position overexposure
    overexposed_positions = []
    single_exposure = portfolio_summary.get("single_ticker_exposure", {})
    exit_plans = exit_plan.get("exitPlans", [])
    for plan in exit_plans:
        ticker = plan.get("ticker", "")
        pos_type = plan.get("type", "SEMI_CORE")
        exposure = single_exposure.get(ticker, 0)
        limit = _MAX_SINGLE_EXPOSURE.get(pos_type, 10)
        if exposure >= limit:
            overexposed_positions.append({
                "symbol": ticker,
                "type": pos_type,
                "exposurePct": round(exposure, 1),
                "limitPct": limit,
            })

    return {
        "elevatedExposure": elevated_exposure,
        "highRiskExposure": high_risk_exposure,
        "concentratedSectors": concentrated_sectors,
        "buyExitConflicts": buy_exit_conflicts,
        "highBetaRiskConflicts": high_beta_conflicts,
        "leveragedEtfRiskConflicts": leveraged_conflicts,
        "overexposedPositions": overexposed_positions,
    }


# --------------- Overall Position Bias ---------------

def compute_overall_bias(exit_plan: dict, position_pct: float) -> str:
    """Determine overall portfolio bias from exit-plan summary and exposure."""
    summary = exit_plan.get("summary", {})
    exit_count = summary.get("exitCount", 0)
    trim_count = summary.get("trimCount", 0)
    watch_count = summary.get("watchCount", 0)

    if exit_count > 0 or position_pct > 80:
        return "EXIT_RISK"
    elif trim_count >= 2 or position_pct > 70:
        return "RISK_CONTROL"
    elif trim_count > 0 or position_pct > 65:
        return "DEFENSIVE_REDUCE"
    elif watch_count > 0:
        return "SELECTIVE_TRIM"
    else:
        return "HOLD_CORE"


# --------------- Action Bucket Builder ---------------

def build_action_buckets(exit_plan: dict, prechecks: dict) -> dict:
    """Group positions into hold/watch/trim/exit/avoidAdding buckets."""
    hold = []
    watch = []
    trim = []
    exit_bucket = []
    avoid_adding = []

    for plan in exit_plan.get("exitPlans", []):
        ticker = plan.get("ticker", "")
        action = plan.get("action", "HOLD")
        reasoning = plan.get("reasoning", [])
        first_reason = reasoning[0] if reasoning else "No signal triggered."

        if action == "HOLD":
            hold.append({"symbol": ticker, "reason": first_reason})
        elif action in ("WATCH", "WATCH_PULLBACK"):
            watch.append({"symbol": ticker, "reason": first_reason})
        elif action in ("TRIM_PROFIT", "TRIM_RISK", "REDUCE_1_3", "REDUCE_1_2", "REDUCE_2_3"):
            trim.append({
                "symbol": ticker,
                "suggestedAction": action,
                "reason": first_reason,
            })
            avoid_adding.append({
                "symbol": ticker,
                "reason": f"Exit-plan has {action} signal.",
            })
        elif action == "EXIT":
            exit_bucket.append({"symbol": ticker, "reason": first_reason})
            avoid_adding.append({
                "symbol": ticker,
                "reason": "Exit signal triggered.",
            })

    # Also add overexposed positions to avoid-adding
    seen = {item["symbol"] for item in avoid_adding}
    for pos in prechecks.get("overexposedPositions", []):
        if pos["symbol"] not in seen:
            avoid_adding.append({
                "symbol": pos["symbol"],
                "reason": f"Position exposure ({pos['exposurePct']}%) exceeds {pos['type']} limit ({pos['limitPct']}%).",
            })
            seen.add(pos["symbol"])

    return {
        "hold": hold,
        "watch": watch,
        "trim": trim,
        "exit": exit_bucket,
        "avoidAdding": avoid_adding,
    }


# --------------- DeepSeek Prompt ---------------

_SYSTEM_PROMPT = """You are a position management and risk-audit assistant.

You do not fetch market data.
You do not invent prices.
You do not invent moving averages, support, resistance, returns, or indicators.
You do not recalculate the exit plan.
You only analyze the structured JSON provided by the application.

The user is a long-term low-buy investor focused on AI and semiconductor supply chains.
The user prefers core positions, avoids overtrading, and uses limit orders.

Your job:
1. Explain the exit-plan in plain English (Chinese is preferred for user-facing text).
2. Group positions into hold, watch, trim, exit, and avoid-adding buckets.
3. Detect conflicts between daily buy candidates and exit-plan signals.
4. Warn about concentration, high-beta risk, leveraged ETF risk, and event risk.
5. Explain whether each position's risk is technical, profit-taking, trend-break, or portfolio-concentration related.
6. Explain the trend context for each position — distinguish pullbacks from real breakdowns.
7. Produce a concise final instruction.

Trend Context Rules:
- When interpreting exit signals, distinguish short-term weakness from medium-term or long-term trend damage.
- Do not treat a 20-day moving average break as a full exit signal for CORE positions if:
  - price remains above MA50,
  - MA50 slope is positive,
  - the stock has not broken recent swing lows,
  - and relative strength vs SMH is not persistently negative.
- For CORE positions, explain whether weakness is: normal pullback, short-term break, medium trend break, long trend break, or persistent underperformance.
- For SEMI_CORE positions, be more cautious than CORE but still avoid mechanical selling on a single short-term signal.
- For HIGH_BETA positions, risk control should remain strict.
- Use the trendStatus field (STRONG_UPTREND, PULLBACK_IN_UPTREND, SHORT_TERM_BREAK_ONLY, MEDIUM_TREND_BREAK, LONG_TREND_BREAK, RELATIVE_UNDERPERFORMER) to guide explanations.

General Rules:
- Never invent prices, indicators, or signals.
- Never override the deterministic action from exitPlan.
- If exitPlan says EXIT, do not soften it to HOLD.
- If exitPlan says TRIM or REDUCE, explain why and do not recommend adding.
- If dailyPlan recommends buying a symbol that exitPlan says TRIM/EXIT, flag a conflict.
- If globalBrief says high beta is not allowed, warn about HIGH_BETA positions.
- If portfolio exposure is elevated or high, favor trimming over adding.
- Keep the final answer concise and practical.
- Use Chinese for user-facing text fields.
- Return valid JSON only, no markdown fences.

Pullback Add-on Rules:
When analyzing positions, also distinguish between:
1. Buyable pullback — medium-term trend intact, above MA50, MA50 rising, swing low not broken, RS not persistently negative, sector not weak.
2. Normal pullback — short-term break only, still above MA50.
3. Breakdown — below MA50, swing low broken, or deeply negative RS.
4. Persistent underperformance — weak RS across all timeframes.

A buyable pullback is allowed only when:
- medium-term trend is intact,
- price is above or near MA50,
- MA50 slope is positive,
- recent swing low is not broken,
- relative strength vs SMH is not persistently negative,
- sector trend is not weak,
- and portfolio exposure allows adding.

Do not recommend adding to a position that the rule engine marks as DO_NOT_ADD or REDUCE_INSTEAD.
For CORE positions, buyable pullbacks may justify ADD_SMALL or ADD_NORMAL.
For SEMI_CORE positions, only ADD_SMALL is usually appropriate.
For HIGH_BETA positions, default to DO_NOT_ADD unless the rule engine explicitly marks ADD_DEEP_ONLY.
For LEVERAGED_ETF positions, do not recommend pullback adding.

If pullbackAddPlan is provided, explain which pullbacks are buyable, which are watch-only,
which positions should not be averaged down, and whether adding conflicts with portfolio exposure."""

_OUTPUT_SCHEMA = {
    "timestamp": "ISO8601 string",
    "overallPositionBias": "HOLD_CORE|SELECTIVE_TRIM|DEFENSIVE_REDUCE|RISK_CONTROL|EXIT_RISK",
    "oneLineSummary": "一句话总结",
    "userFacingSummary": "2-3句面向用户的总结",
    "portfolioRead": {
        "exposureComment": "仓位暴露评价",
        "concentrationComment": "集中度评价",
        "trendComment": "趋势评价",
        "riskComment": "风险评价",
    },
    "actionBuckets": {
        "hold": [{"symbol": "str", "reason": "str"}],
        "watch": [{"symbol": "str", "reason": "str"}],
        "trim": [{"symbol": "str", "suggestedAction": "TRIM_1_3|TRIM_1_2|REDUCE_2_3", "reason": "str"}],
        "exit": [{"symbol": "str", "reason": "str"}],
        "avoidAdding": [{"symbol": "str", "reason": "str"}],
    },
    "conflicts": [{"symbol": "str", "conflictType": "str", "severity": "LOW|MEDIUM|HIGH", "explanation": "str"}],
    "positionExplanations": [{
        "symbol": "str",
        "action": "HOLD|WATCH|TRIM_1_3|TRIM_1_2|REDUCE_2_3|EXIT",
        "plainEnglishReason": "str",
        "whatWouldChangeTheDecision": "str",
        "nextTriggerToWatch": "str",
    }],
    "riskWarnings": ["str"],
    "finalInstruction": "str",
}


def build_ai_exit_prompt(
    exit_plan: dict,
    portfolio_summary: dict,
    prechecks: dict,
    overall_bias: str,
    daily_plan: Optional[dict] = None,
    global_brief: Optional[dict] = None,
    pullback_add_plan: Optional[dict] = None,
) -> str:
    """Build the user prompt with all structured data for DeepSeek."""
    input_data = {
        "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "userProfile": USER_PROFILE,
        "overallPositionBias_deterministic": overall_bias,
        "portfolioSummary": {
            "accountValue": portfolio_summary.get("account_value", 0),
            "cash": portfolio_summary.get("cash", 0),
            "investedValue": portfolio_summary.get("invested_value", 0),
            "exposurePct": portfolio_summary.get("position_pct", 0),
            "bucketExposure": portfolio_summary.get("bucket_exposure", {}),
        },
        "exitPlan": exit_plan,
        "prechecks": prechecks,
    }

    if daily_plan:
        input_data["dailyPlan"] = daily_plan
    if global_brief:
        input_data["globalBrief"] = global_brief
    if pullback_add_plan:
        input_data["pullbackAddPlan"] = pullback_add_plan

    user_prompt = (
        "Analyze the following structured position data.\n\n"
        "Return JSON only. Do not include markdown. Do not invent data.\n"
        "Use the deterministic overallPositionBias provided — explain it, do not override it.\n\n"
        f"Input:\n{json.dumps(input_data, ensure_ascii=False, default=str)}\n\n"
        f"Required output schema:\n{json.dumps(_OUTPUT_SCHEMA, ensure_ascii=False)}\n"
    )
    return user_prompt


# --------------- DeepSeek Caller ---------------

def call_deepseek_exit_analysis(user_prompt: str) -> Optional[dict]:
    """Call DeepSeek with the exit analysis prompt. Returns parsed dict or None."""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        logger.info("[ai-exit] DEEPSEEK_API_KEY not set, using fallback")
        return None

    base_url = "https://api.deepseek.com"
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

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
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 4000,
                "temperature": 0.1,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            logger.warning("[ai-exit] DeepSeek returned empty content")
            return None

        # Strip markdown fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            cleaned = cleaned.rsplit("```", 1)[0].strip()

        parsed = json.loads(cleaned)
        logger.info(f"[ai-exit] DeepSeek returned valid JSON ({len(content)} chars)")
        return parsed

    except json.JSONDecodeError as e:
        logger.warning(f"[ai-exit] Failed to parse DeepSeek JSON: {e}")
        return None
    except Exception as e:
        logger.warning(f"[ai-exit] DeepSeek call failed: {e}")
        return None


# --------------- Output Validator ---------------

_VALID_BIASES = {"HOLD_CORE", "SELECTIVE_TRIM", "DEFENSIVE_REDUCE", "RISK_CONTROL", "EXIT_RISK"}
_VALID_ACTIONS = {"HOLD", "WATCH", "WATCH_PULLBACK", "TRIM_PROFIT", "TRIM_RISK", "REDUCE_1_3", "REDUCE_1_2", "REDUCE_2_3", "EXIT"}


def validate_ai_exit_output(response: dict) -> bool:
    """Validate the AI response has required structure. Returns True if valid."""
    if not isinstance(response, dict):
        return False

    required_keys = [
        "overallPositionBias", "oneLineSummary", "userFacingSummary",
        "portfolioRead", "actionBuckets", "positionExplanations",
        "riskWarnings", "finalInstruction",
    ]
    for key in required_keys:
        if key not in response:
            logger.warning(f"[ai-exit] Missing key in AI response: {key}")
            return False

    if response.get("overallPositionBias") not in _VALID_BIASES:
        logger.warning(f"[ai-exit] Invalid bias: {response.get('overallPositionBias')}")
        return False

    buckets = response.get("actionBuckets", {})
    if not isinstance(buckets, dict):
        return False
    for bucket_name in ("hold", "watch", "trim", "exit", "avoidAdding"):
        if not isinstance(buckets.get(bucket_name, []), list):
            return False

    return True


# --------------- Deterministic Fallback ---------------

def build_fallback_exit_analysis(
    exit_plan: dict,
    portfolio_summary: dict,
    prechecks: dict,
    overall_bias: str,
) -> dict:
    """Build complete AI exit analysis from deterministic data only."""
    position_pct = portfolio_summary.get("position_pct", 0)

    # Portfolio read
    if position_pct < 50:
        exposure_comment = "仓位暴露较低，有充足空间持有核心仓位。"
    elif position_pct < 65:
        exposure_comment = "仓位适中，新建仓应有选择性。"
    elif position_pct < 75:
        exposure_comment = "仓位偏高，优先减持弱势或高位品种。"
    else:
        exposure_comment = "仓位过高，风控优先于新建仓。"

    concentrated = prechecks.get("concentratedSectors", [])
    if concentrated:
        sectors = ", ".join(s["sectorGroup"] for s in concentrated)
        concentration_comment = f"组合集中于 {sectors}，除非有特别好的信号否则避免继续加仓该板块。"
    else:
        concentration_comment = "各板块分布尚可，无明显过度集中。"

    # Trend comment based on MA20 status
    exit_plans = exit_plan.get("exitPlans", [])
    above_ma20_count = sum(1 for p in exit_plans if p.get("daysBelowMA20", 0) == 0)
    total = len(exit_plans) or 1
    if above_ma20_count / total > 0.7:
        trend_comment = "多数持仓维持在20日均线上方，趋势健康。"
    elif above_ma20_count / total > 0.4:
        trend_comment = "部分持仓跌破20日均线，趋势质量开始下降。"
    else:
        trend_comment = "大量持仓低于20日均线，组合趋势明显走弱。"

    summary = exit_plan.get("summary", {})
    if summary.get("exitCount", 0) > 0:
        risk_comment = "至少有一个持仓触发了退出信号，需要优先处理。"
    elif summary.get("trimCount", 0) > 0:
        risk_comment = "有持仓触发了止盈或风控减仓信号。"
    else:
        risk_comment = "暂无强制退出或减仓信号。"

    # Action buckets
    buckets = build_action_buckets(exit_plan, prechecks)

    # Conflicts
    conflicts = []
    for c in prechecks.get("buyExitConflicts", []):
        conflicts.append({
            "symbol": c["symbol"],
            "conflictType": "BUY_SIGNAL_BUT_EXIT_SIGNAL",
            "severity": "HIGH",
            "explanation": f"每日计划建议买入 {c['symbol']}，但退出计划建议 {c['exitPlanAction']}。在信号消除前不要加仓。",
        })
    for ticker in prechecks.get("highBetaRiskConflicts", []):
        conflicts.append({
            "symbol": ticker,
            "conflictType": "GLOBAL_RISK_OFF_BUT_HIGH_BETA_HOLDING",
            "severity": "MEDIUM",
            "explanation": f"全球市场处于风险偏好降低状态，{ticker} 作为高弹性品种需要关注减仓。",
        })

    # Position explanations
    position_explanations = []
    for plan in exit_plans:
        ticker = plan.get("ticker", "")
        action = plan.get("action", "HOLD")
        reasoning = plan.get("reasoning", [])
        first_reason = reasoning[0] if reasoning else "规则引擎生成的信号。"

        risk_plan = plan.get("riskPlan", [])
        trim_plan = plan.get("trimPlan", [])
        next_trigger = "无可用触发条件。"
        if risk_plan:
            next_trigger = risk_plan[0].get("trigger", next_trigger)
        elif trim_plan:
            next_trigger = trim_plan[0].get("trigger", next_trigger)

        position_explanations.append({
            "symbol": ticker,
            "action": action,
            "plainEnglishReason": first_reason,
            "whatWouldChangeTheDecision": "关注MA20、MA50、支撑位、阻力位或盈亏变化。",
            "nextTriggerToWatch": next_trigger,
        })

    # Risk warnings
    risk_warnings = []
    if prechecks.get("buyExitConflicts"):
        risk_warnings.append("不要加仓退出计划建议减持的品种。")
    if prechecks.get("concentratedSectors"):
        risk_warnings.append("避免继续增加已过度集中的板块仓位。")
    if prechecks.get("highBetaRiskConflicts"):
        risk_warnings.append("高弹性品种在市场风险偏好降低时需要更紧的风控。")
    if prechecks.get("leveragedEtfRiskConflicts"):
        risk_warnings.append("杠杆ETF不适合长期持有，注意及时止盈止损。")
    if prechecks.get("highRiskExposure"):
        risk_warnings.append("整体仓位过高，风控优先于新建仓。")

    hold_count = summary.get("holdCount", 0)
    watch_count = summary.get("watchCount", 0)
    trim_count = summary.get("trimCount", 0)
    exit_count = summary.get("exitCount", 0)

    return {
        "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "overallPositionBias": overall_bias,
        "oneLineSummary": f"退出计划: {hold_count}持有, {watch_count}观察, {trim_count}减仓, {exit_count}退出。",
        "userFacingSummary": "这是基于规则引擎的确定性分析结果（AI 解读暂不可用）。请按照退出计划的信号执行，不要加仓已触发减仓或退出信号的品种。",
        "portfolioRead": {
            "exposureComment": exposure_comment,
            "concentrationComment": concentration_comment,
            "trendComment": trend_comment,
            "riskComment": risk_comment,
        },
        "actionBuckets": buckets,
        "conflicts": conflicts,
        "positionExplanations": position_explanations,
        "riskWarnings": risk_warnings,
        "finalInstruction": "按照规则引擎的退出计划执行。持有核心仓位，减仓触发信号的品种，不加仓已标记减持/退出的标的。",
    }


# --------------- Main Entry Point ---------------

def generate_ai_exit_analysis(
    portfolio_summary: dict,
    exit_plan: dict,
    daily_plan: Optional[dict] = None,
    global_brief: Optional[dict] = None,
    pullback_add_plan: Optional[dict] = None,
) -> dict:
    """Generate AI-enhanced exit analysis.

    Orchestrates: prechecks → bias → prompt → DeepSeek → validate → return (or fallback).

    Args:
        portfolio_summary: dict from PortfolioSummary (account_value, cash, position_pct, bucket_exposure, etc.)
        exit_plan: dict from generate_exit_plan() (marketRegime, portfolioRisk, summary, exitPlans)
        daily_plan: optional dict from daily-plan endpoint
        global_brief: optional dict from global-market-brief endpoint
        pullback_add_plan: optional dict from generate_pullback_add_plan()

    Returns:
        AIExitAnalysisResponse dict
    """
    # Step 1: Deterministic pre-checks
    prechecks = compute_exit_prechecks(portfolio_summary, exit_plan, daily_plan, global_brief)

    # Step 2: Compute overall bias
    position_pct = portfolio_summary.get("position_pct", 0)
    overall_bias = compute_overall_bias(exit_plan, position_pct)

    # Step 3: Try DeepSeek
    provider = os.getenv("LLM_PROVIDER", "none").lower()
    if provider not in ("none", ""):
        user_prompt = build_ai_exit_prompt(
            exit_plan, portfolio_summary, prechecks, overall_bias, daily_plan, global_brief, pullback_add_plan
        )
        ai_result = call_deepseek_exit_analysis(user_prompt)

        if ai_result and validate_ai_exit_output(ai_result):
            # Ensure AI doesn't override deterministic bias
            ai_result["overallPositionBias"] = overall_bias
            if "timestamp" not in ai_result:
                ai_result["timestamp"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
            logger.info("[ai-exit] Using DeepSeek analysis")
            return ai_result
        else:
            logger.info("[ai-exit] DeepSeek failed validation, using fallback")

    # Step 4: Fallback
    logger.info("[ai-exit] Using deterministic fallback")
    return build_fallback_exit_analysis(exit_plan, portfolio_summary, prechecks, overall_bias)
