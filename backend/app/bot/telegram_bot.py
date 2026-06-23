"""Telegram bot using python-telegram-bot."""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# Add parent path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

load_dotenv()

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.bot.commands import (
    handle_avoid,
    handle_natural_language,
    handle_portfolio,
    handle_sleep,
    handle_strong,
    handle_summary,
)

logger = logging.getLogger(__name__)

# Telegram message length limit
MAX_MSG_LEN = 4096


async def _send_long_message(update: Update, text: str):
    """Send a message, splitting if too long."""
    if len(text) <= MAX_MSG_LEN:
        await update.message.reply_text(text)
        return

    # Split by lines
    lines = text.split("\n")
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > MAX_MSG_LEN:
            await update.message.reply_text(chunk)
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        await update.message.reply_text(chunk)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"AI 产业链盯盘助手已就绪。\n"
        f"你的 Chat ID: {chat_id}\n\n"
        f"可用命令:\n"
        f"/summary - 市场总览\n"
        f"/sleep - 睡觉 limit 计划\n"
        f"/strong - 强势板块\n"
        f"/avoid - 不能接的票\n"
        f"/portfolio - 持仓概览\n\n"
        f"也可以直接用自然语言对话。"
    )


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("正在获取行情数据...")
    text = handle_summary()
    await _send_long_message(update, text)


async def cmd_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("正在生成睡觉计划...")
    text = handle_sleep()
    await _send_long_message(update, text)


async def cmd_strong(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = handle_strong()
    await _send_long_message(update, text)


async def cmd_avoid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = handle_avoid()
    await _send_long_message(update, text)


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = handle_portfolio()
    await _send_long_message(update, text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle natural language messages."""
    text = update.message.text or ""
    if not text.strip():
        return

    reply = handle_natural_language(text)
    await _send_long_message(update, reply)


def main():
    """Start the Telegram bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set. Bot cannot start.")
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    print("Starting Telegram bot...")

    app = Application.builder().token(token).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("sleep", cmd_sleep))
    app.add_handler(CommandHandler("strong", cmd_strong))
    app.add_handler(CommandHandler("avoid", cmd_avoid))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    main()
