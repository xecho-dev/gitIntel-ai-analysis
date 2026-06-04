"""
GitIntel 图片生成服务
使用通义千问 API 生成 AI 插图（用于 PDF 报告美化）
同步版本，避免在 async handler 中使用 asyncio.run()
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("image_generation")

try:
    import dashscope
    from dashscope import ImageSynthesis

    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False
    logger.warning("dashscope 未安装，图片生成功能不可用")


IMAGE_SIZE = "1024*1024"
IMAGE_STYLE = "<flat illustration>"


def _get_prompt_for_cover(repo_name: str, tech_stack: list[str]) -> str:
    tech_str = ", ".join(tech_stack[:3]) if tech_stack else "software"
    return (
        f"A professional software analysis dashboard cover image for project '{repo_name}'. "
        f"Tech stack: {tech_str}. "
        f"Style: modern tech illustration with code snippets, architecture diagrams, "
        f"data visualization elements. Clean, corporate, blue-purple gradient theme. "
        f"No text, no people. High quality 3D render."
    )


def _get_prompt_for_architecture(architecture_style: str, complexity: str) -> str:
    return (
        f"A clean technical diagram showing {architecture_style} software architecture pattern. "
        f"Complexity level: {complexity}. "
        f"Illustration style: blueprint, technical drawing, blueprint grid background. "
        f"Showing interconnected modules, layers, and data flow arrows. "
        f"No text, no people. Professional blue color scheme."
    )


def _get_prompt_for_quality(grade: str, score: str) -> str:
    return (
        f"A clean code quality visualization showing a {grade} grade software metrics dashboard. "
        f"Score: {score}. "
        f"Illustration: code editor with syntax highlighting, quality checkmarks, "
        f"bug detection indicators, clean code icons. "
        f"Style: modern flat design, green and teal accent colors. "
        f"No text, no people."
    )


def _get_prompt_for_dependency(risk_level: str) -> str:
    risk_desc = {
        "h": "high risk dependency vulnerabilities",
        "m": "medium risk dependency health check",
        "l": "low risk secure dependencies",
    }.get(risk_level, "software dependencies")
    return (
        f"A visualization of software package dependencies network. "
        f"Showing {risk_desc}. "
        f"Illustration: node-graph with packages connected by lines, "
        f"colored dots for vulnerability status (red/yellow/green). "
        f"Style: modern tech infographic, dark background with neon accents. "
        f"No text, no people."
    )


def _get_prompt_for_optimization() -> str:
    return (
        "A clean optimization and performance improvement illustration. "
        "Showing before/after comparison, speed meters, efficiency charts. "
        "Illustration: gear icons, rocket ship, performance graphs trending up. "
        "Style: modern flat design, purple and orange accent colors. "
        "No text, no people."
    )


def _download_image_sync(url: str) -> Optional[bytes]:
    """同步下载图片到内存"""
    try:
        import httpx

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            if response.status_code == 200:
                return response.content
            logger.error(f"下载图片失败 HTTP {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"下载图片异常: {type(e).__name__}: {e}")
        return None


def generate_image_sync(
    prompt: str,
    api_key: Optional[str] = None,
) -> Optional[bytes]:
    """
    同步调用通义千问生成图片，轮询直到完成，返回图片字节流。
    """
    if not DASHSCOPE_AVAILABLE:
        logger.error("dashscope 未安装，无法生成图片")
        return None

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("未设置 OPENAI_API_KEY 环境变量")
        return None

    try:
        import time

        dashscope.api_key = api_key

        response = ImageSynthesis.call(
            model=ImageSynthesis.Models.wanx_v1,
            prompt=prompt,
            size=IMAGE_SIZE,
            style=IMAGE_STYLE,
        )

        if response.status_code != 200:
            logger.error(f"通义千问 API 错误: {response.code} - {response.message}")
            return None

        # 获取任务 ID 并轮询结果
        task_id = response.output.task_id
        logger.info(f"图片生成任务已提交: {task_id}，等待完成...")

        for _ in range(30):  # 最多等 30 秒
            time.sleep(1)
            result_response = ImageSynthesis.fetch(task_id)
            if result_response.status_code == 200:
                status = result_response.output.task_status
                if status == "SUCCEEDED":
                    for result in result_response.output.results:
                        if result.url:
                            img_data = _download_image_sync(result.url)
                            if img_data:
                                logger.info(f"图片生成成功: {result.url}")
                                return img_data
                    logger.error("通义千问返回了空结果")
                    return None
                elif status == "FAILED":
                    logger.error(f"图片生成失败: {result_response.output.message}")
                    return None
                # 继续轮询
            else:
                logger.error(f"获取任务状态失败: {result_response.code}")
                return None

        logger.error("图片生成超时（30秒）")
        return None

    except Exception as e:
        logger.error(f"生成图片异常: {type(e).__name__}: {e}")
        return None


# 缓存
_image_cache: dict[str, bytes] = {}


def get_cached_image_sync(key: str, prompt: str) -> Optional[bytes]:
    """同步获取缓存的图片，如果未缓存则生成并缓存"""
    if key in _image_cache:
        logger.debug(f"使用缓存图片: {key}")
        return _image_cache[key]

    logger.info(f"生成新图片: {key}")
    image_bytes = generate_image_sync(prompt)
    if image_bytes:
        _image_cache[key] = image_bytes
    return image_bytes


def clear_cache():
    """清空图片缓存"""
    _image_cache.clear()
