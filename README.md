# AI 产业链盯盘助手 MVP

个人 AI 产业链盯盘助手，帮助跟踪 AI 半导体产业链行情，生成盯盘报告和交易计划建议。

## 项目架构概览

```
ai-chain-watchlist-mvp/
├── docker-compose.yml          # Docker 部署配置
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # FastAPI 入口，注册所有路由
│       ├── api/                # HTTP API 路由层
│       │   ├── routes_market.py      # 行情/watchlist/sleep-plan 接口
│       │   ├── routes_portfolio.py   # 仓位查询/更新/交易记录 接口
│       │   ├── routes_chat.py        # 对话接口（关键词意图 + 自由聊天）
│       │   └── routes_knowledge.py   # 知识库上传/查看 接口
│       ├── core/               # 核心业务逻辑
│       │   ├── config_loader.py      # 加载 YAML/JSON 配置
│       │   ├── llm_client.py         # DeepSeek/OpenAI 调用（润色+自由聊天）
│       │   ├── market_data.py        # yfinance 行情拉取
│       │   ├── models.py            # Pydantic 数据模型
│       │   ├── portfolio.py         # 仓位分析（暴露度/集中度）
│       │   ├── report.py            # 报告生成（盯盘报告/睡觉挂单计划）
│       │   └── scoring.py           # 板块评分/大盘强弱判断
│       ├── config/             # 运行时配置文件（可通过 API 修改）
│       │   ├── watchlist.yaml       # 板块/标的定义
│       │   ├── rules.yaml           # 风控规则和交易参数
│       │   ├── portfolio.json       # 当前仓位数据
│       │   └── knowledge.md         # 交易策略知识库（通过 API 自动维护）
│       ├── bot/                # Telegram Bot
│       │   ├── telegram_bot.py      # Bot 主入口
│       │   └── commands.py          # Bot 命令处理
│       └── jobs/               # 定时任务
│           └── scheduler.py         # APScheduler 定时报告推送
```

## 核心数据流

```
yfinance 行情 → scoring.py(板块评分) → report.py(生成报告)
                                      ↓
portfolio.json(仓位) → portfolio.py → 动作建议 + sleep plan
                                      ↓
                              llm_client.py(DeepSeek 润色/对话)
                                      ↓
                              API 返回 / Telegram 推送
```

## API 接口一览

| Method | Path | 功能 |
|--------|------|------|
| GET | `/` | 服务状态 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/watchlist` | 查看 watchlist 配置 |
| GET | `/api/market/summary` | 行情摘要 + 板块评分 |
| POST | `/api/refresh` | 强制刷新行情缓存 |
| GET | `/api/sleep-plan` | 睡觉 Limit 挂单计划 |
| GET | `/api/portfolio` | 查看当前仓位分析 |
| PUT | `/api/portfolio` | 替换完整仓位 |
| POST | `/api/portfolio/trade` | 记录买入/卖出交易 |
| POST | `/api/chat` | 对话（关键词意图 + 自由问答） |
| GET | `/api/knowledge` | 查看知识库内容 |
| POST | `/api/knowledge/upload` | 上传文字/图片学习策略 |

## Chat 意图分类逻辑

`routes_chat.py` 中通过关键词匹配路由到不同处理：

| 关键词 | 处理 |
|--------|------|
| 睡觉/limit/睡前/挂单 | 返回 sleep plan |
| 能加/加仓/可以买/候选 | 返回加仓候选 |
| 不能接/不要买/别碰 | 返回风险标的 |
| 强势/强链路/哪个板块强 | 返回强势板块 |
| 光通信/光互连 | 光通信板块详情 |
| 半导体设备/设备 | 核心半导体板块详情 |
| 报告/盯盘/总结/overview | 完整盯盘报告（LLM 润色） |
| 其他 | 自由对话（带市场上下文发给 DeepSeek） |

## 配置文件说明

### watchlist.yaml
定义跟踪的板块和标的：
- `benchmarks.core_indices`: 大盘基准（QQQ/SMH/SOXX）
- `buckets`: 各细分板块（名称/角色/标的列表）

### rules.yaml
风控规则和交易参数（阈值、仓位限制等）

### portfolio.json
当前仓位：`account_value`, `cash`, `positions[]`（ticker/shares/avg_cost/bucket）

### knowledge.md
通过 `/api/knowledge/upload` 自动维护的交易策略知识库，会注入到 LLM 对话上下文中。

## 环境变量 (.env)

| 变量 | 必填 | 说明 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | 否 | Telegram Bot token |
| `TELEGRAM_CHAT_ID` | 否 | 推送目标 chat ID |
| `LLM_PROVIDER` | 是 | `none` / `deepseek` / `openai` |
| `DEEPSEEK_API_KEY` | 当 provider=deepseek | DeepSeek API Key |
| `DEEPSEEK_MODEL` | 否 | 默认 `deepseek-chat` |
| `DEEPSEEK_VISION_MODEL` | 否 | 图片识别模型，默认 `deepseek-chat` |
| `OPENAI_API_KEY` | 当 provider=openai | OpenAI API Key |
| `OPENAI_MODEL` | 否 | 默认 `gpt-4o-mini` |
| `MARKET_DATA_PROVIDER` | 否 | 默认 `yfinance` |
| `APP_TIMEZONE` | 否 | 默认 `Asia/Singapore` |

## 技术栈

- Python 3.11+
- FastAPI + Uvicorn
- APScheduler
- python-telegram-bot
- yfinance
- pandas
- pydantic
- DeepSeek API (OpenAI-compatible)

## 本地运行

```bash
cd backend
cp .env.example .env
# 编辑 .env 填入配置
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Docker 运行

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env
docker compose up --build
```

## 扩展点

- **添加新板块**: 编辑 `config/watchlist.yaml` 添加新 bucket
- **修改风控规则**: 编辑 `config/rules.yaml`
- **添加新 chat 意图**: 在 `routes_chat.py` 的 if-elif 链中添加关键词分支
- **接入新 LLM**: 在 `llm_client.py` 添加新 provider
- **添加新 API**: 创建 `routes_xxx.py`，在 `main.py` 注册 router

```bash
# 健康检查
curl http://localhost:8000/api/health

# 获取行情摘要
curl http://localhost:8000/api/market/summary

# 获取睡觉 limit 计划
curl http://localhost:8000/api/sleep-plan

# 获取组合信息
curl http://localhost:8000/api/portfolio

# 获取 watchlist
curl http://localhost:8000/api/watchlist

# 对话
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"现在怎么看"}'

# 刷新行情
curl -X POST http://localhost:8000/api/refresh
```

## 编辑 portfolio.json

手动编辑 `backend/app/config/portfolio.json`：

```json
{
  "as_of": "manual",
  "account_value": 40000,
  "cash": 28000,
  "positions": [
    {
      "ticker": "AMAT",
      "shares": 10,
      "avg_cost": 240.5,
      "manual_value": 2400,
      "bucket": "core_ai_semis",
      "intent": "core"
    }
  ]
}
```

## 风险说明

- **本项目不自动下单。** 所有交易结论只是盯盘建议。
- **本项目不构成投资建议。** 仅用于个人交易计划整理。
- **行情数据可能延迟或缺失。** yfinance 免费数据有延迟。
- **yfinance 不适合作为严肃交易的唯一实时行情源。**
- **真实交易前必须人工确认。**
- NVDA 只作为 AI 情绪风向标，不作为核心持仓推荐。
