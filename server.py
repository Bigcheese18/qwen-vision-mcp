#!/usr/bin/env python3
"""
Qwen3-VL 视觉 MCP 服务器
=====================

让 Claude Code 通过 MCP 工具调用 Qwen3-VL 分析本地图片：
  - OCR / 文档识别
  - 截图 / UI 元素理解
  - 图表、表格转 Markdown 等

后端走阿里云百炼（DashScope）的 OpenAI 兼容接口。
配置通过 .env（或环境变量）读取：
  QWV_API_KEY   必填，百炼 API Key
  QWV_MODEL     可选，默认 qwen3-vl-235b-a22b-thinking
  QWV_BASE_URL  可选，默认 DashScope OpenAI 兼容地址
"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Windows 控制台默认用 GBK，MCP stdio 需要 UTF-8，否则中文结果会乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

import httpx

try:
    from dotenv import load_dotenv

    # 显式加载脚本同目录的 .env，避免依赖启动时的工作目录
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from mcp.server.fastmcp import FastMCP

DASHSCOPE_BASE = os.getenv(
    "QWV_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
).rstrip("/")
API_KEY = os.getenv("QWV_API_KEY", "").strip()
MODEL = os.getenv("QWV_MODEL", "qwen3-vl-235b-a22b-thinking")

if not API_KEY:
    print("错误: 未设置 QWV_API_KEY（请在 .env 中配置）", file=sys.stderr)
    sys.exit(1)

mcp = FastMCP("qwen-vision")

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

# 复用连接（避免每次请求重建 TCP/TLS）+ 内存缓存（同一图+同一问题不重复调 API）
_client = httpx.Client(timeout=180)
_cache: dict[str, str] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 128


def _read_image_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


def _call_qwen(data_url: str, prompt: str, fast: bool = False) -> str:
    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "temperature": 0.2,
    }
    if fast:
        # 跳过思考过程。小图/简单任务实测约快 2.4x；大图瓶颈在视觉 token 处理，收益很小
        body["enable_thinking"] = False
    resp = _client.post(
        f"{DASHSCOPE_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json=body,
    )
    if resp.status_code != 200:
        return f"错误：API 返回 {resp.status_code}: {resp.text[:500]}"
    data = resp.json()
    message = data["choices"][0]["message"]
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    content = str(content or "").strip()
    if not content:
        # thinking 模型的思考过程兜底
        content = str(message.get("reasoning_content") or "").strip()
    return content or "(模型未返回任何内容)"


DEFAULT_PROMPT = """请客观、准确地描述这张图片的内容，用中文回答：
1. 这是什么类型的图片（网页截图 / 文档 / 照片 / 图表…）；
2. 图中主要的元素（文字、图片、图标、按钮、菜单等），可读的文字请原样转录；
3. 从上到下、从左到右的布局结构；
4. 整体色调与视觉风格。
注意：只描述图片中实际可见的内容，不要推测或补充图中没有的信息；文字若被截断或看不清，请明确标注[截断]或[看不清]。"""


@mcp.tool()
def analyze_image(file_path: str, prompt: str = DEFAULT_PROMPT, fast: bool = False) -> str:
    """用 Qwen3-VL 分析本地图片文件（OCR / 识别截图与 UI 元素 / 理解图表）。

    Args:
        file_path: 图片文件的绝对或相对路径。
        prompt: 想对图片提的问题，例如 "提取图中的文字"、"识别这个按钮的坐标"。
                不传则使用内置的通用描述模板（含客观转录 + 防推测约束）。
        fast: True 时关闭 thinking。小图/简单任务实测约快 2.4x；大图收益很小
              （瓶颈在视觉 token 处理而非思考），可保持默认。
    """
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        return f"错误：找不到图片文件 {file_path}"
    if path.suffix.lower() not in SUPPORTED_EXTS:
        return (
            f"错误：不支持的文件类型 {path.suffix}，"
            f"仅支持 {', '.join(sorted(SUPPORTED_EXTS))}"
        )
    try:
        data_url = _read_image_data_url(path)
    except Exception as e:  # noqa: BLE001
        return f"错误：读取图片失败：{e}"

    key = hashlib.sha256(
        (data_url + "\x00" + prompt + "\x00" + ("fast" if fast else "full")).encode("utf-8")
    ).hexdigest()
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached

    try:
        result = _call_qwen(data_url, prompt, fast=fast)
    except Exception as e:  # noqa: BLE001
        return f"错误：调用 Qwen3-VL 失败：{e}"

    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[key] = result
    return result


def _analyze_many(paths: list[str], prompt: str, fast: bool = False) -> dict[str, str]:
    """并发分析多张图，返回 {路径: 结果}。"""
    with ThreadPoolExecutor(max_workers=min(len(paths), 8)) as ex:
        futs = [ex.submit(analyze_image, p, prompt, fast) for p in paths]
        return {p: f.result() for p, f in zip(paths, futs)}


@mcp.tool()
def analyze_images_batch(
    image_paths: list[str], prompt: str = DEFAULT_PROMPT, fast: bool = False
) -> str:
    """并行分析多张本地图片（同一个 prompt）。适合批量 OCR / 批量截图审查。

    Args:
        image_paths: 图片文件的绝对或相对路径列表。
        prompt: 想对每张图提的问题；不传则用内置通用模板。
        fast: 同 analyze_image，关闭 thinking 提速。
    """
    if not image_paths:
        return "错误：未提供图片路径"
    results = _analyze_many(image_paths, prompt, fast)
    return "\n\n".join(f"[{p}]\n{r}" for p, r in results.items())


if __name__ == "__main__":
    mcp.run(transport="stdio")
