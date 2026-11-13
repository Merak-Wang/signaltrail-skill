from __future__ import annotations

from typing import Any

import httpx

CHALLENGE_TEXTS = (
    "verify you are human",
    "checking your browser",
    "are you a robot",
    "unusual traffic",
    "security check",
    "your request is being verified",
    "enable javascript and cookies",
    "robot check",
    "sina visitor system",
    "client challenge",
    "transferring to the website...",
)
RATE_LIMIT_TEXTS = (
    "temporarily limited",
    "temporarily restricted",
    "too many requests",
    "rate limit exceeded",
)


async def read_bounded_response(
    response: httpx.Response, max_bytes: int,
) -> tuple[bytes, bool]:
    """处理：流式读取响应，超出字节上限立即停止并标记截断。
    输入：已打开的 HTTP 响应和允许保留的字节数。
    输出：有界响应字节与截断标记，供索引和正文采集共用。
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        remaining = max_bytes - total
        chunks.append(chunk[:remaining])
        total += len(chunk)
        if total > max_bytes:
            return b"".join(chunks), True
    return b"".join(chunks), False


def classify_access_text(
    http_status: int | None,
    title: str,
    body: str,
    *,
    iframe_detected: bool = False,
) -> dict[str, Any]:
    """处理：统一识别 HTTP 与浏览器采集中的访问失败类型。
    输入：
    - ``http_status``：页面最近一次 HTTP 状态码；无网络响应时可为空。
    - ``title``：来源提供的标题文本；会清理空白，并用于过滤、身份或展示。
    - ``body``：正文或 HTML 文本；保存前只作为数据处理。
    - ``iframe_detected``：访问分类器是否在页面中发现验证码或登录挑战 iframe。
    输出：required 仅表示识别到挑战提示；rate_limited 独立表示限流，
      iframe_detected 保留页面线索，matched_text 记录命中的提示。
    """
    # 页面开头保留挑战提示，避免正文后部或页脚的文字触发误判。
    haystack = f"{title} {body[:500]}".lower()
    rate_limited_text = next((text for text in RATE_LIMIT_TEXTS if text in haystack), None)
    matched = next((text for text in CHALLENGE_TEXTS if text in haystack), None)
    rate_limited = http_status == 429 or rate_limited_text is not None
    required = matched is not None
    return {
        "required": required,
        "rate_limited": rate_limited,
        "matched_text": rate_limited_text or matched,
        "iframe_detected": iframe_detected,
    }
