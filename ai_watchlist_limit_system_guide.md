# AI 盯盘与 Limit 低吸系统设计指南

## 1. 目标

本系统用于辅助长线低吸 AI 产业链股票，而不是做日内短线交易。系统每天根据市场环境、个股强弱、支撑位、压力位、波动率和账户仓位，自动输出：

- 今天哪些股票值得关注
- 哪些股票可以买入 / 低吸 / 等待 / 不买
- 每只股票的 limit 价格
- 每档买入金额
- 当天总买入上限
- 不建议买入的原因

核心原则：

> 先判断市场环境，再选择股票，再计算 limit，最后由仓位约束决定买入金额。

系统不应该因为某只股票上涨就追高，也不应该因为某只股票下跌就无脑补仓。

---

## 2. 账户假设

默认账户参数：

```text
account_total = 15000
current_position_value = user_current_position_value
cash_available = account_total - current_position_value
```

默认仓位规则：

```text
normal_target_position = 0.45 to 0.55
aggressive_target_position = 0.60
max_position = 0.70
```

如果当前总仓位已经超过 55%，系统应明显降低新增买入金额。

如果当前总仓位超过 70%，系统只允许极端低吸，不允许普通加仓。

---

## 3. 股票池分类

系统必须先给每只股票打上 category 标签。不同 category 使用不同 limit 公式和不同买入金额。

### 3.1 核心仓 Core

适合长期分批低吸，可以作为组合主仓。

```text
Core:
NVDA, AVGO, TSM, ASML, AMAT, KLAC, LRCX, SMH, SOXX, QQQ
```

特点：

- 可以作为长期核心仓
- limit 可以相对浅一点
- 每档买入金额可以较大
- 但如果用户已有较多同类仓位，需要降权

---

### 3.2 半核心 Semi-Core

有长期逻辑，但波动更大，不应比 Core 更重。

```text
Semi-Core:
AMD, MRVL, COHR, LITE, TER, FORM, KLIC, DELL, HPE, CLS
```

特点：

- 可以小到中等仓位参与
- 需要更深的 limit
- 如果当天弱于板块，不应重仓补

---

### 3.3 周期仓 Cyclical

受行业周期、财报和价格周期影响较大。

```text
Cyclical:
MU, SNDK, DRAM, INTC, AAOI
```

特点：

- 不适合越跌越补
- 财报日前后必须降低金额
- 财报后必须看市场反应，不只看财报数字

---

### 3.4 高 Beta 弹性仓 High-Beta

只适合小仓观察或极端低吸。

```text
High-Beta:
ALAB, CRDO, SMCI, IREN, CRWV, NBIS, CORZ, AAOI
```

特点：

- 波动大
- limit 必须更深
- 每档金额必须小
- 不作为核心仓

---

### 3.5 杠杆 / 工具类 ETF Leveraged / Tool

```text
Leveraged_or_Tool:
RAM
```

规则：

- 不作为长期核心仓
- 只允许极小观察仓
- 默认不推荐买入
- 如果买入，每档金额通常不超过账户总额的 0.5% 到 1%

---

## 4. 市场环境判断 Market Regime

每天先判断市场环境，再决定今天买入力度。

参考指数 / ETF：

```text
QQQ, SMH, SOXX, SOX
```

需要的数据：

```text
current_price
open_price
previous_close
intraday_high
intraday_low
VWAP, optional
```

### 4.1 计算 ETF 当日状态

```text
return_from_open = (current_price - open_price) / open_price
return_from_prev_close = (current_price - previous_close) / previous_close
```

### 4.2 市场环境分类

```text
if QQQ > open and SMH > open and SOXX > open:
    market_regime = "strong"
elif QQQ near open and at least one of SMH/SOXX > open:
    market_regime = "neutral"
elif QQQ < open and SMH < open and SOXX < open:
    market_regime = "weak"
elif SMH and SOXX are both sharply below open and making new intraday lows:
    market_regime = "selloff"
else:
    market_regime = "neutral"
```

建议阈值：

```text
near_open = within +/- 0.3%
sharply_below_open = below open by more than 1.5%
```

### 4.3 市场环境对应买入力度

```text
market_multiplier = {
    "strong": 1.20,
    "neutral": 1.00,
    "weak": 0.70,
    "selloff": 0.50,
    "event": 0.50
}
```

---

## 5. 个股强弱判断

每只股票需要计算以下指标。

### 5.1 相对开盘强弱

```text
open_strength = (current_price - open_price) / open_price
```

分类：

```text
if open_strength > 0.01:
    open_status = "strong"
elif open_strength >= 0:
    open_status = "stable"
elif open_strength > -0.01:
    open_status = "slightly_weak"
else:
    open_status = "weak"
```

---

### 5.2 相对板块强弱

半导体相关个股默认和 SMH 或 SOXX 比较。

```text
stock_return_today = (current_price - previous_close) / previous_close
sector_return_today = (SMH_current - SMH_previous_close) / SMH_previous_close
relative_strength = stock_return_today - sector_return_today
```

分类：

```text
if relative_strength > 0.02:
    relative_status = "strong_vs_sector"
elif relative_strength >= 0:
    relative_status = "slightly_strong_vs_sector"
elif relative_strength > -0.02:
    relative_status = "slightly_weak_vs_sector"
else:
    relative_status = "weak_vs_sector"
```

---

### 5.3 距离支撑位

```text
support_distance = (current_price - nearest_support) / current_price
```

分类：

```text
if support_distance <= 0.02:
    support_status = "near_support"
elif support_distance <= 0.05:
    support_status = "wait_for_pullback"
else:
    support_status = "far_from_support"
```

---

### 5.4 距离压力位

```text
resistance_distance = (nearest_resistance - current_price) / current_price
```

分类：

```text
if resistance_distance < 0.02:
    resistance_status = "too_close_to_resistance"
elif resistance_distance < 0.05:
    resistance_status = "limited_upside"
else:
    resistance_status = "enough_room"
```

如果一只股票距离压力位太近，不能追高，只能等回踩。

---

### 5.5 15 分钟动量

```text
momentum_15m = (current_price - price_15m_ago) / price_15m_ago
```

分类：

```text
if momentum_15m > 0.008:
    momentum_status = "chasing_risk"
elif momentum_15m < -0.01:
    momentum_status = "falling_fast"
else:
    momentum_status = "stable"
```

规则：

- 如果正在快速拉升，不追，limit 下调。
- 如果正在快速下杀，limit 也要下调，避免接飞刀。
- 如果稳定在支撑位附近，最适合挂 limit。

---

## 6. 股票评分 Stock Score

系统给每只股票打 0 到 100 分。

### 6.1 类别分数

```text
category_score = {
    "Core": 100,
    "Semi-Core": 80,
    "Cyclical": 60,
    "High-Beta": 40,
    "Leveraged_or_Tool": 20
}
```

### 6.2 分数公式

```text
score =
    0.30 * category_score
  + 0.20 * relative_strength_score
  + 0.20 * support_score
  + 0.15 * trend_score
  + 0.10 * volume_score
  - 0.10 * event_penalty
  - 0.10 * concentration_penalty
```

如果暂时没有 volume 或 trend 数据，可以先用以下简化版：

```text
score =
    0.35 * category_score
  + 0.25 * relative_strength_score
  + 0.25 * support_score
  + 0.15 * open_strength_score
  - event_penalty
  - concentration_penalty
```

### 6.3 分数含义

```text
score >= 80: preferred_buy_candidate
score 65-79: buy_candidate_if_limit_reached
score 50-64: watch_only
score < 50: do_not_buy
```

---

## 7. Limit 价格计算

系统不要只用一个公式。建议同时计算多个候选价，然后取中位数 median，避免某个指标过度偏离。

需要的数据：

```text
current_price
nearest_support
next_support
ATR
swing_high
swing_low
market_regime
category
```

---

### 7.1 支撑位法

普通环境：

```text
support_limit_1 = nearest_support * 1.003
support_limit_2 = next_support * 1.003
```

弱势环境：

```text
support_limit_1 = nearest_support * 0.995
support_limit_2 = next_support * 0.995
```

解释：

- 普通环境挂在支撑位略上方，避免差一点没成交。
- 弱势环境挂在支撑位略下方，避免支撑被轻微跌破后接得太早。

---

### 7.2 百分比折价法

Core：

```text
percent_limit_1 = current_price * 0.985
percent_limit_2 = current_price * 0.960
```

Semi-Core：

```text
percent_limit_1 = current_price * 0.970
percent_limit_2 = current_price * 0.930
```

Cyclical：

```text
percent_limit_1 = current_price * 0.970
percent_limit_2 = current_price * 0.920
```

High-Beta：

```text
percent_limit_1 = current_price * 0.940
percent_limit_2 = current_price * 0.880
```

Leveraged / Tool：

```text
percent_limit_1 = current_price * 0.920
percent_limit_2 = current_price * 0.850
```

---

### 7.3 ATR 波动法

Core：

```text
atr_limit_1 = current_price - 0.5 * ATR
atr_limit_2 = current_price - 1.0 * ATR
```

Semi-Core：

```text
atr_limit_1 = current_price - 0.6 * ATR
atr_limit_2 = current_price - 1.2 * ATR
```

Cyclical：

```text
atr_limit_1 = current_price - 0.7 * ATR
atr_limit_2 = current_price - 1.3 * ATR
```

High-Beta：

```text
atr_limit_1 = current_price - 0.8 * ATR
atr_limit_2 = current_price - 1.5 * ATR
```

Leveraged / Tool：

```text
atr_limit_1 = current_price - 1.0 * ATR
atr_limit_2 = current_price - 2.0 * ATR
```

如果没有 ATR，可以临时用 intraday range 近似：

```text
estimated_ATR = intraday_high - intraday_low
```

但更推荐使用 14 日 ATR。

---

### 7.4 斐波那契回撤法

输入：

```text
swing_high
swing_low
```

计算：

```text
fib_382 = swing_high - (swing_high - swing_low) * 0.382
fib_500 = swing_high - (swing_high - swing_low) * 0.500
fib_618 = swing_high - (swing_high - swing_low) * 0.618
```

使用规则：

```text
if category == "Core" and stock is strong:
    fib_limit_1 = fib_382
    fib_limit_2 = fib_500
elif category in ["Core", "Semi-Core"]:
    fib_limit_1 = fib_500
    fib_limit_2 = fib_618
else:
    fib_limit_1 = fib_618
    fib_limit_2 = None
```

---

### 7.5 最终 Limit 聚合公式

Core：

```text
limit_1 = median(nearest_support, current_price * 0.985, current_price - 0.5 * ATR)
limit_2 = median(next_support, current_price * 0.960, current_price - 1.0 * ATR)
```

Semi-Core：

```text
limit_1 = median(nearest_support, current_price * 0.970, current_price - 0.6 * ATR)
limit_2 = median(next_support, current_price * 0.930, current_price - 1.2 * ATR)
```

Cyclical：

```text
limit_1 = median(nearest_support, current_price * 0.970, current_price - 0.7 * ATR)
limit_2 = median(next_support, current_price * 0.920, current_price - 1.3 * ATR)
```

High-Beta：

```text
limit_1 = median(nearest_support, current_price * 0.940, current_price - 0.8 * ATR)
limit_2 = median(next_support, current_price * 0.880, current_price - 1.5 * ATR)
```

Leveraged / Tool：

```text
limit_1 = median(nearest_support, current_price * 0.920, current_price - 1.0 * ATR)
limit_2 = median(next_support, current_price * 0.850, current_price - 2.0 * ATR)
```

---

## 8. Limit 调整规则

计算出基础 limit 后，再根据市场和个股状态调整。

### 8.1 市场弱势时

```text
if market_regime == "weak":
    limit_1 = limit_1 * 0.99
    limit_2 = limit_2 * 0.985
```

### 8.2 市场杀跌时

```text
if market_regime == "selloff":
    limit_1 = limit_1 * 0.985
    limit_2 = limit_2 * 0.970
```

### 8.3 股票正在快速拉升

```text
if momentum_status == "chasing_risk":
    do_not_raise_limit = True
    limit_1 = min(limit_1, current_price * 0.985)
```

### 8.4 股票正在快速下杀

```text
if momentum_status == "falling_fast":
    limit_1 = limit_1 * 0.985
    limit_2 = limit_2 * 0.970
```

### 8.5 距离压力太近

```text
if resistance_status == "too_close_to_resistance":
    action = "wait"
    reduce_order_amount_by = 0.5
```

---

## 9. 买入金额计算

### 9.1 基础金额

针对 15k 账户：

```text
base_amount = {
    "Core": 400,
    "Semi-Core": 300,
    "Cyclical": 250,
    "High-Beta": 150,
    "Leveraged_or_Tool": 75
}
```

### 9.2 市场倍数

```text
market_multiplier = {
    "strong": 1.20,
    "neutral": 1.00,
    "weak": 0.70,
    "selloff": 0.50,
    "event": 0.50
}
```

### 9.3 个股倍数

```text
stock_multiplier = {
    "strong": 1.20,
    "stable": 1.00,
    "slightly_weak": 0.80,
    "weak": 0.60,
    "very_weak": 0.40
}
```

### 9.4 仓位倍数

```text
position_ratio = current_position_value / account_total

if position_ratio < 0.40:
    position_multiplier = 1.10
elif position_ratio < 0.55:
    position_multiplier = 1.00
elif position_ratio < 0.70:
    position_multiplier = 0.50
else:
    position_multiplier = 0.20
```

### 9.5 最终金额

```text
order_amount = base_amount[category] * market_multiplier * stock_multiplier * position_multiplier
```

金额需要取整：

```text
order_amount = round_to_nearest_50(order_amount)
```

### 9.6 每日总金额限制

```text
daily_total_limit = {
    "strong": 2000,
    "neutral": 1500,
    "weak": 1000,
    "selloff": 800,
    "event": 800
}
```

如果所有候选订单金额加总超过 daily_total_limit，则按 score 从高到低保留订单，直到金额不超过上限。

---

## 10. 集中度控制

系统必须避免越买越集中。

### 10.1 单票上限

```text
single_stock_max = account_total * 0.15
```

如果是 Semi-Core：

```text
single_stock_max = account_total * 0.10
```

如果是 High-Beta：

```text
single_stock_max = account_total * 0.05
```

如果是 Leveraged / Tool：

```text
single_stock_max = account_total * 0.02
```

---

### 10.2 产业链上限

```text
chain_max = account_total * 0.40
```

例如：

```text
Equipment_chain = AMAT + KLAC + LRCX + ASML
Memory_chain = MU + SNDK + DRAM + RAM
AI_network_chain = AVGO + MRVL + AMD + ALAB + CRDO
Optical_chain = COHR + LITE + AAOI + CIEN
```

如果某条产业链已经超过 35% 到 40%，系统应降低该链条股票的 score 和 order_amount。

---

## 11. 事件日规则

### 11.1 财报前

财报前不做大额补仓。

```text
if earnings_within_24h:
    order_amount = order_amount * 0.5
    limit_1 = limit_1 * 0.98
    limit_2 = limit_2 * 0.95
```

### 11.2 财报后

财报后不只看财报数字，而要看市场反应。

规则：

```text
if earnings_strong and stock_gaps_up and then holds_above_open:
    action = "hold_existing_or_small_pullback_buy"
elif earnings_strong and stock_gaps_up_then_fades_below_open:
    action = "wait_or_small_deep_limit"
elif earnings_bad and stock_down_large:
    action = "do_not_catch_first_knife"
```

财报后 limit 可用：

```text
limit_1 = post_earnings_intraday_low * 0.995
limit_2 = post_earnings_intraday_low * 0.950
```

---

## 12. 候选股票筛选逻辑

每天最多输出：

```text
2 Core candidates
1 Semi-Core or Cyclical candidate
1 High-Beta or observation candidate
```

不要每天输出十几只股票，否则用户会买太散。

筛选顺序：

```text
1. Exclude stocks with score < 50
2. Exclude stocks too close to resistance
3. Exclude stocks from already overweight chains
4. Rank by score
5. Keep top 2 Core stocks
6. Keep top 1 Semi-Core/Cyclical stock
7. Optional: keep top 1 High-Beta stock only if score > 70
```

---

## 13. 输出格式

系统每天应输出固定格式，方便用户快速执行。

示例：

```markdown
## Market Regime

- QQQ: weak / neutral / strong
- SMH: weak / neutral / strong
- SOXX: weak / neutral / strong
- Today action level: low / medium / high
- Daily max buy amount: $1,500

## Recommended Orders

| Ticker | Category | Action | Limit 1 | Amount 1 | Limit 2 | Amount 2 | Reason |
|---|---|---|---:|---:|---:|---:|---|
| TSM | Core | Buy pullback | 434 | $400 | - | - | Core, stronger than SMH, near support |
| AVGO | Core | Buy pullback | 373 | $400 | - | - | Core AI ASIC, not extended |
| MRVL | Semi-Core | Small buy only | 265 | $300 | 255 | $200 | Weak today but near support |
| MU | Cyclical | Small post-earnings buy | 1135 | $350 | 1090 | $250 | Earnings strong but high volatility |

## Do Not Buy / Wait

| Ticker | Reason |
|---|---|
| RAM | Leveraged ETF, not suitable for long-term core |
| DRAM | Too much overlap with MU |
| AAOI | Weak versus optical group |

## Total Planned Buy

- Total if all orders fill: $1,900
- Estimated position after fill: 50% to 55%
- Cash remaining: safe
```

---

## 14. Copilot Implementation Notes

Recommended modules:

```text
1. data_loader.py
   - fetch prices, open, high, low, previous close, VWAP, ATR, support, resistance

2. classifier.py
   - map ticker to category and chain

3. market_regime.py
   - classify strong / neutral / weak / selloff / event

4. scoring.py
   - calculate stock score

5. limit_calculator.py
   - calculate limit_1 and limit_2

6. position_manager.py
   - apply account-level and chain-level constraints

7. report_generator.py
   - generate markdown output
```

Suggested main flow:

```python
def generate_daily_plan(account, holdings, market_data, watchlist):
    market_regime = classify_market_regime(market_data)
    candidates = []

    for ticker in watchlist:
        data = market_data[ticker]
        category = classify_category(ticker)
        chain = classify_chain(ticker)

        score = calculate_score(
            ticker=ticker,
            data=data,
            category=category,
            chain=chain,
            market_regime=market_regime,
            holdings=holdings,
            account=account,
        )

        if score < 50:
            continue

        limit_1, limit_2 = calculate_limits(
            data=data,
            category=category,
            market_regime=market_regime,
        )

        amount_1, amount_2 = calculate_order_amounts(
            score=score,
            category=category,
            market_regime=market_regime,
            holdings=holdings,
            account=account,
            ticker=ticker,
            chain=chain,
        )

        candidates.append({
            "ticker": ticker,
            "category": category,
            "chain": chain,
            "score": score,
            "limit_1": limit_1,
            "amount_1": amount_1,
            "limit_2": limit_2,
            "amount_2": amount_2,
        })

    final_orders = apply_daily_total_limit(candidates, account, market_regime)
    return generate_markdown_report(final_orders, market_regime, account)
```

---

## 15. Hard Rules

The system must always apply these hard rules:

```text
1. Do not buy every stock in the watchlist.
2. Do not raise limit just because price is running away.
3. If an order does not fill, keep cash.
4. If current position exceeds 55%, reduce new order amounts.
5. If current position exceeds 70%, only allow extreme pullback buys.
6. Do not let one stock exceed 15% of total account.
7. Do not let High-Beta stocks exceed 5% each.
8. Do not let Leveraged ETF positions exceed 2% total account.
9. Do not over-concentrate in one chain.
10. If user already owns a chain heavily, reduce score for that chain.
11. Earnings days require smaller size and deeper limits.
12. Strong earnings plus high-open fade is not an automatic buy.
13. Weak stock below open and below sector should not be averaged down aggressively.
14. Core stocks get priority over theme ETFs.
15. Cash is also a position.
```

---

## 16. User-Specific Preference Defaults

For this user:

```text
account_total = 15000
style = long_term_pullback_buying
avoid_too_many_positions = True
prefer_core_positions = True
elastic_positions_small = True
avoid_chasing = True
```

Current preference:

```text
Primary Core Priority:
1. AVGO
2. TSM
3. NVDA only if price is attractive
4. ASML if account size allows

Already Owned / Lower Add Priority:
AMAT, ASX, KLAC, LRCX, MU

Small / Elastic Only:
MRVL, AMD, COHR, LITE, ALAB, CRDO

Avoid or Observation Only:
RAM, DRAM, AAOI, high-beta compute rental names unless extreme pullback
```

---

## 17. Final Design Principle

The system should act like a disciplined long-term buyer:

> Buy core stocks on pullbacks, avoid chasing, keep position size controlled, and never allow one daily idea to override the long-term portfolio structure.

The output should always answer:

```text
1. What is the market regime today?
2. Which 2 to 4 stocks are worth buying today?
3. What are the exact limit prices?
4. How much should be bought at each limit?
5. Which stocks should not be bought today and why?
6. What will total portfolio exposure be if all orders fill?
```
