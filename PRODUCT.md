# AI Chain Watchlist — 产品说明

## 产品定位

**AI 产业链盯盘助手** — 面向个人投资者的 AI 半导体产业链智能盯盘系统。通过自动化数据采集、技术分析、AI 决策辅助，提供从「看盘 → 决策 → 手动执行 → 持仓管理」的全流程交易支持。

**核心理念：手动执行、系统决策**

本系统永远不会自动下单。所有买卖信号都以「建议 + 限价」形式呈现，由用户在券商端手动执行，执行后通过自然语言录入交易记录。系统根据交易历史感知冷却期、仓位暴露度和信号冲突，持续优化下一轮决策。

---

## 核心功能

### 🧠 决策中心（新）

一站式决策聚合面板，整合所有引擎输出并检测信号冲突：

- **买入计划** — 当前评分通过的限价挂单候选
- **退出信号** — 持仓中非 HOLD 动作的标的
- **回调加仓** — 符合加仓条件的持仓标的及限价
- **信号冲突检测** — 自动识别引擎间的矛盾：
  - 买入 vs 退出信号冲突
  - 回调加仓 vs 退出信号冲突
  - 近期卖出后回买矛盾
  - 冷却期内重复加仓
  - 暴露度超限警告
  - 反复摊平检测
- **交易活动摘要** — 各标的近期买卖状态、冷却期

---

### 🌍 全球市场概览

每日自动采集全球主要市场数据，覆盖：

| 分类 | 标的 |
|------|------|
| 🇺🇸 美股指数 | SPY (S&P 500)、QQQ (纳斯达克)、DIA (道琼斯) |
| 🌏 亚太 | EWH (香港)、EWJ (日本)、FXI (中国) |
| 🇨🇳 中概股 | KWEB (中概互联ETF) |
| 🥇 贵金属 | 黄金 (XAU/USD)、白银 (SLV)、铂金 (PPLT) |
| 🔧 工业金属 | 铜 (CPER) |
| 🔋 新能源 | 锂电池 (LIT) |
| ⛽ 能源 | 原油 (USO) |
| ₿ 加密货币 | BTC/USD |

- 定时采集：每日 08:00（欧美收盘后）、18:00（亚太收盘后）
- 按需查看：点击即显示最新缓存数据

---

### 🎯 每日交易计划

自动生成限价买单计划：

1. **市场环境判断** — 判断当前市场处于强势/中性/弱势
2. **个股评分** — 对关注列表中 37 只标的综合评分（趋势、动量、相对强度）
3. **限价计算** — 三种方法取中位数（支撑位、均线回调、ATR 折扣）
4. **金额分配** — 按评分权重分配，总额不超过账户 30%
5. **自动过滤** — 已持仓标的不出现在新买计划中
6. **冷却期过滤**（新）— 近期风控卖出的标的自动排除（5日冷却），减仓标的短暂排除（2日冷却）

---

### 📉 持仓管理（退出 + 回调加仓）

一站式持仓决策面板：

#### 退出策略
- **趋势感知退出规则**：结合短/中/长期趋势状态和板块强弱
- **多级动作**：HOLD / WATCH / WATCH_PULLBACK / TRIM_PROFIT / TRIM_RISK / REDUCE_1_3 / REDUCE_1_2 / EXIT
- **交易历史上下文**（新）：每个持仓标注近期是否加仓/减仓、冷却状态
- **AI 增强分析**：DeepSeek 大模型给出综合解读和操作建议

#### 回调加仓
- **回调分类**：BUYABLE_PULLBACK / NORMAL_PULLBACK / WATCH_ONLY / BREAKDOWN_DO_NOT_ADD / REDUCE_INSTEAD
- **分仓位类型**：核心仓位允许正常加仓，高弹性仓位仅深度回调加仓，杠杆 ETF 禁止加仓
- **限价建议**：两级加仓价位 + 取消条件
- **冷却期标注**（新）：处于冷却期的标的标记 ⏸️，防止冲动操作

---

### 📝 交易记录（新）

基于 Trade Ledger 的完整交易生命周期管理：

- **自然语言录入**：「买了100股NVDA 均价135」→ 自动解析并确认
- **交易台账**：所有买/卖记录存储在 `trades` 表，是仓位的唯一真源
- **仓位重建**：从交易记录自动计算当前持仓（数量、均价、盈亏）
- **现金追踪**：入金/出金独立记录，现金余额从交易推算
- **历史查询**：按标的/时间筛选交易，支持修改备注

---

### 💬 智能对话

支持多种交互模式：

| 触发词 | 功能 |
|--------|------|
| 「睡觉」/「挂单」 | 生成睡前限价挂单计划 |
| 「仓位」 | 显示当前持仓概览 |
| 「报告」/「盯盘」 | 生成完整市场报告 |
| 「评分 NVDA」 | 单只标的评分详情 |
| 「查 NVDA」 | 单只标的技术分析 |
| 「加现金 5000」 | 记录入金 |
| 自由提问 | 基于市场数据 + 知识库的 AI 回答 |

---

### 📊 仪表盘

技术分析总览报告：
- 各板块涨跌热力图
- 均线/RSI/MACD 关键信号
- 板块 vs 基准（SMH、SOXX）相对强度

---

## 关注标的

以 AI 半导体产业链为核心，覆盖 7 大板块：

| 板块 | 角色 | 代表标的 |
|------|------|----------|
| 核心 AI 半导体 | core | TSM, ASML, AMAT, LRCX, KLAC, MU, AVGO |
| 弹性 AI 半导体 | beta | MRVL, CRDO, SNDK, ASX, AMKR, TER, FORM, ALAB |
| 封测/载板 | beta | KLIC, AMKR, ASX |
| 光通信/互连 | beta | COHR, LITE, AAOI, CRDO, MRVL, AVGO |
| AI 服务器/整机 | beta | SMCI, DELL, HPE, CLS |
| AI 电力/数据中心 | core | VRT, ETN, PWR, CEG, GEV, IREN |
| AI 云/算力高β | high_beta | CRWV, NBIS, IREN, CORZ |

基准指数：QQQ、SMH、SOXX、SOX Index
参考标的：NVDA（市场情绪指标）

---

## 技术架构

```
┌─────────────────────────────────────────────────┐
│                   Frontend                       │
│         React + TypeScript + Tailwind            │
│         Chat UI (PWA-ready) + 5 按钮             │
│                Port 80 (Nginx)                   │
└────────────────────┬────────────────────────────┘
                     │ /api/*
┌────────────────────▼────────────────────────────┐
│                   Backend                        │
│              FastAPI + Uvicorn                    │
│                Port 8000                         │
├──────────────────────────────────────────────────┤
│  Market Data    │  LLM Client   │  Scheduler    │
│  (Polygon/yf)   │  (DeepSeek)   │  (APScheduler)│
├──────────────────────────────────────────────────┤
│  Scoring Engine │ Exit Engine │ Pullback Engine  │
│  Tech Analysis  │ Trend Context│ Global Market  │
├──────────────────────────────────────────────────┤
│  Decision Center │ Conflict Detector │           │
│  Trade Ledger    │ Trade History Ctx  │           │
├──────────────────────────────────────────────────┤
│        SQLite (Portfolio DB + Trade Ledger)       │
│           JSON (Config / Cache)                  │
└──────────────────────────────────────────────────┘
```

### 数据模型

| 表 | 职责 |
|------|------|
| `trades` | 交易台账（唯一仓位真源） |
| `cash_transactions` | 入金/出金记录 |
| `manual_order_plans` | 系统建议的手动挂单计划 |
| `position_snapshots` | 仓位快照（用于历史回溯） |
| `positions` | 当前持仓（由 trades 自动同步） |
| `portfolio_meta` | 账户级配置（总资产、现金） |
| `schema_version` | 数据库迁移版本 |

---

## API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/decisions` | GET | 决策中心（聚合所有引擎 + 冲突检测） |
| `/api/daily-plan` | GET | 每日买入计划（含冷却过滤） |
| `/api/exit-plan` | GET | 持仓退出计划（含交易历史上下文） |
| `/api/pullback-add-plan` | GET | 回调加仓计划（含冷却标注） |
| `/api/global-market` | GET | 全球市场快照 |
| `/api/trades` | GET/POST | 交易记录查询/新增 |
| `/api/trades/{id}` | PATCH/DELETE | 交易记录修改/删除 |
| `/api/positions/rebuild` | GET | 从交易重建仓位 |
| `/api/cash-transactions` | GET/POST | 现金流水 |
| `/api/manual-order-plans` | GET/POST | 手动挂单计划管理 |
| `/api/trade-history-context` | GET | 交易历史上下文（冷却期等） |
| `/api/market/summary` | GET | 市场摘要报告 |
| `/api/market/dashboard` | GET | 技术分析仪表盘 |
| `/api/market/technical/{ticker}` | GET | 单只标的技术分析 |
| `/api/market/score/{ticker}` | GET | 单只标的评分 |
| `/api/portfolio` | GET | 仓位概览 |
| `/api/chat` | POST | AI 对话 |
| `/api/health` | GET | 健康检查 |

---

## 数据源

| 数据源 | 用途 | 说明 |
|--------|------|------|
| Polygon Proxy | 美股实时行情 | 主数据源，37 只标的逐个获取 |
| yfinance | 美股历史数据 | 技术分析用 (MA/RSI/MACD) |
| Twelve Data | 全球市场快照 | 14 只全球标的，每日 2 次采样 |
| DeepSeek API | AI 分析 | 持仓管理增强、对话回答 |

---

## 部署方式

**Docker Compose 一键部署：**

```bash
docker-compose up -d
```

- `backend` 容器：FastAPI + Scheduler，持久化数据卷
- `frontend` 容器：Nginx 静态站 + API 反向代理
- 自动重启策略：`unless-stopped`

---

## 定时任务

| 任务 | 时间 | 说明 |
|------|------|------|
| 市场报告 | 每 30 分钟 | 生成市场总结，推送 Telegram |
| 全球市场早间快照 | 08:00 CST | 采集欧美收盘数据 |
| 全球市场晚间快照 | 18:00 CST | 采集亚太收盘数据 |

---

## 前端交互

采用 **Chat UI** 风格，所有功能通过对话消息或快捷按钮触发：

### 主按钮栏（5 个常用）

| 按钮 | 功能 |
|------|------|
| 🧠 决策 | 决策中心 — 聚合买卖信号 + 冲突检测 |
| 🌍 全球 | 全球市场概览 |
| 🎯 计划 | 每日限价买单计划 |
| 📉 持仓 | 持仓管理（退出 + 回调加仓） |
| 📝 记交易 | 自然语言录入买卖记录 |

### ⋯更多（展开）

| 按钮 | 功能 |
|------|------|
| 💼 仓位 | 仓位概览 + AI 分析 |
| 📜 交易记录 | 交易台账历史 |
| 🎯 仪表盘 | 技术分析总览 |
| 🛌 挂单 | 睡前限价挂单计划 |

### 交互特性
- Markdown 格式响应（表格、加粗、emoji）
- 实时加载状态
- 连接状态指示器
- AI 增强开关（StatusBar 中切换）
- 交易确认/取消双按钮

---

## 配置项

```env
# LLM
LLM_PROVIDER=deepseek          # deepseek / openai / none
DEEPSEEK_API_KEY=<key>

# 行情数据
MARKET_DATA_PROVIDERS=polygon_proxy,yfinance
POLYGON_PROXY_URL=<url>
POLYGON_PROXY_KEY=<key>

# 全球市场
TWELVE_DATA_API_KEY=<key>

# 通知（可选）
TELEGRAM_BOT_TOKEN=<token>
TELEGRAM_CHAT_ID=<id>
```

---

## 目标用户

个人投资者，专注 AI/半导体产业链，需要：
- 一键查看所有引擎的综合决策建议和信号冲突
- 盘前快速了解全球市场环境
- 自动生成当日限价买单计划
- 系统化管理现有持仓的加仓/减仓决策
- 手动执行后用自然语言记录交易
- 系统自动感知交易历史，避免冲动操作（冷却期、冲突检测）
- 用 AI 辅助理解复杂的多标的持仓状态
