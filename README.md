# AI 产业链盯盘助手 MVP

个人 AI 产业链盯盘助手，帮助跟踪 AI 半导体产业链行情，生成盯盘报告和交易计划建议。

## 功能

- 跟踪 QQQ / SMH / SOXX 大盘强弱
- 分析 AI 产业链各细分板块相对强弱
- 识别高于开盘价并接近日高的加仓候选
- 标记低于开盘价并接近日低的风险标的
- 基于仓位和现金生成动作建议（加仓/持有/减仓/等待）
- 生成睡觉 limit 挂单计划
- 支持 Telegram Bot 对话
- 支持 HTTP API 查看报告
- 定时生成报告并推送到 Telegram

## 技术栈

- Python 3.11+
- FastAPI + Uvicorn
- APScheduler
- python-telegram-bot
- yfinance
- pandas
- pydantic

## 本地运行

```bash
cd backend
cp .env.example .env
# 编辑 .env 填入 Telegram token 等配置
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 运行 Telegram Bot

```bash
cd backend
python -m app.bot.telegram_bot
```

## 运行定时任务

```bash
cd backend
python -m app.jobs.scheduler
```

## Docker 运行

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env
docker compose up --build
```

## 创建 Telegram Bot

1. 在 Telegram 搜索 `@BotFather`
2. 发送 `/newbot`，按提示创建 bot
3. 获取 bot token，填入 `.env` 的 `TELEGRAM_BOT_TOKEN`

## 获取 TELEGRAM_CHAT_ID

1. 给你的 bot 发一条消息
2. 访问 `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. 在返回的 JSON 中找到 `chat.id`
4. 填入 `.env` 的 `TELEGRAM_CHAT_ID`

或者启动 bot 后发送 `/start`，bot 会回复你的 chat_id。

## API 示例

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
