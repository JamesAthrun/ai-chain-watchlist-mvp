"""Knowledge base API - learn from posts/images."""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config_loader import CONFIG_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

KNOWLEDGE_FILE = CONFIG_DIR / "knowledge.md"


class KnowledgeInput(BaseModel):
    text: Optional[str] = None
    image_base64: Optional[str] = None  # base64 encoded image


@router.get("/knowledge")
async def get_knowledge():
    """Get current knowledge base content."""
    if not KNOWLEDGE_FILE.exists():
        return {"content": "", "message": "Knowledge base is empty."}
    content = KNOWLEDGE_FILE.read_text(encoding="utf-8")
    return {"content": content}


@router.post("/knowledge/upload")
async def upload_knowledge(input_data: KnowledgeInput):
    """Upload text or image to learn from and update knowledge base."""
    if not input_data.text and not input_data.image_base64:
        return {"status": "error", "message": "Provide either text or image_base64"}

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"status": "error", "message": "DEEPSEEK_API_KEY not configured"}

    # Step 1: Extract content from image if provided
    raw_content = input_data.text or ""
    if input_data.image_base64:
        extracted = _extract_from_image(api_key, input_data.image_base64)
        if extracted:
            raw_content = f"{raw_content}\n\n[图片内容]:\n{extracted}" if raw_content else extracted

    if not raw_content.strip():
        return {"status": "error", "message": "No content could be extracted"}

    # Step 2: Summarize into structured knowledge points
    new_points = _summarize_to_knowledge(api_key, raw_content)
    if not new_points:
        return {"status": "error", "message": "Failed to extract knowledge points"}

    # Step 3: Read existing knowledge and merge
    existing = ""
    if KNOWLEDGE_FILE.exists():
        existing = KNOWLEDGE_FILE.read_text(encoding="utf-8")

    merged = _merge_knowledge(api_key, existing, new_points)

    # Step 4: Write back
    KNOWLEDGE_FILE.write_text(merged, encoding="utf-8")

    return {
        "status": "ok",
        "new_points": new_points,
        "message": "Knowledge base updated successfully",
    }


def _extract_from_image(api_key: str, image_base64: str) -> str:
    """Use DeepSeek vision to extract text/insights from image."""
    base_url = "https://api.deepseek.com"
    model = os.getenv("DEEPSEEK_VISION_MODEL", "deepseek-chat")

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
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                            },
                            {
                                "type": "text",
                                "text": "请提取这张图片中的所有文字内容和关键交易策略信息。如果是小红书推文截图，请提取核心观点。",
                            },
                        ],
                    }
                ],
                "max_tokens": 2000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.warning(f"Image extraction failed: {e}")
        return ""


def _summarize_to_knowledge(api_key: str, raw_content: str) -> str:
    """Summarize raw content into structured knowledge points."""
    base_url = "https://api.deepseek.com"
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    system_prompt = (
        "你是一个交易策略分析师。请从以下内容中提取核心交易策略和方法论要点。\n"
        "输出格式要求：\n"
        "- 用简洁的要点形式\n"
        "- 按类别分组（仓位管理/进场条件/出场止损/板块轮动/情绪择时/其他）\n"
        "- 只提取有价值的策略信息，忽略无关内容\n"
        "- 不要编造内容，只从原文提取"
    )

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
                    {"role": "user", "content": f"请提取以下内容的策略要点:\n\n{raw_content}"},
                ],
                "max_tokens": 1500,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        logger.warning(f"Knowledge summarization failed: {e}")
        return ""


def _merge_knowledge(api_key: str, existing: str, new_points: str) -> str:
    """Merge new knowledge points into existing knowledge base."""
    if not existing.strip():
        header = "# 交易策略知识库\n\n"
        header += f"_最后更新: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n\n"
        return header + new_points

    base_url = "https://api.deepseek.com"
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    system_prompt = (
        "你是一个知识库管理员。请将新的策略要点合并到已有知识库中。\n"
        "规则：\n"
        "- 去重：如果新要点和已有内容重复，不要重复添加\n"
        "- 归类：按已有的分类结构放置新要点\n"
        "- 保留：不要删除或修改已有内容\n"
        "- 补充：如果需要新分类，可以添加\n"
        "- 输出完整的合并后知识库内容（markdown格式）"
    )

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
                    {"role": "user", "content": f"已有知识库:\n{existing}\n\n新提取的要点:\n{new_points}\n\n请输出合并后的完整知识库:"},
                ],
                "max_tokens": 4000,
                "temperature": 0.2,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        merged = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return merged if merged else existing + "\n\n" + new_points
    except Exception as e:
        logger.warning(f"Knowledge merge failed: {e}, appending instead")
        return existing + f"\n\n---\n_新增 ({datetime.now(timezone.utc).strftime('%Y-%m-%d')})_\n\n" + new_points
