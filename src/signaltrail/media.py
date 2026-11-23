from __future__ import annotations

import hashlib
import ipaddress
import socket
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from io import BytesIO
from itertools import chain
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx
from PIL import Image, ImageStat, UnidentifiedImageError

from .config import MediaConfig
from .image_policy import (
    _image_pixels,
    image_resolution_candidates,
    image_variant_groups,
    image_variant_key,
    is_placeholder_image_url,
    normalize_image_candidates,
)
from .storage import write_bytes_atomic
from .utils import read_json, sha256_file, write_json

_ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "GIF": ("image/gif", ".gif"),
    "WEBP": ("image/webp", ".webp"),
}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_USER_AGENT = "DailyIntelligenceMedia/1.0 (+public-news-image-fetcher)"
_PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_PUBLIC_DNS_ENDPOINT = "https://dns.google/resolve"
_IMAGE_CACHE_SCHEMA_VERSION = "1.1"


class ImageDownloadError(ValueError):
    """表示图片 URL、网络响应、格式或安全校验失败。"""
    pass


@dataclass(frozen=True, slots=True)
class DownloadedImage:
    """已通过格式和尺寸检查的图片，保留原始 URL、重定向后 URL 和基于内容哈希的数据根相对路径。
    ETag 和 Last-Modified 供条件请求复用本地文件。
    """
    source_url: str
    resolved_url: str
    local_path: str
    content_type: str
    sha256: str
    byte_size: int
    width: int
    height: int
    reused: bool
    etag: str | None = None
    last_modified: str | None = None


def _utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。
    输入：无显式业务参数：不接收参数；读取系统 UTC 时钟并返回带时区时间。
    """
    return datetime.now(UTC)


def _utc_iso(value: datetime | None = None) -> str:
    """把 UTC 时间格式化为秒级 ISO 字符串。"""
    return (value or _utc_now()).isoformat(timespec="seconds")


def _parse_cache_time(value: object) -> datetime | None:
    """把图片缓存中的 ISO 时间解析为 UTC 时间，非法值返回 None。"""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _image_cache_path(data_dir: Path) -> Path:
    """返回运行数据根中的图片下载缓存文件。"""
    return data_dir / "media" / "image-cache.json"


def _load_image_cache(data_dir: Path) -> dict[str, Any]:
    """读取版本化图片缓存并校验 entries 根对象，损坏时回退为空缓存。
    输出：字段包括 entries、schema_version、updated_at。
    """
    path = _image_cache_path(data_dir)
    if not path.exists():
        return {
            "schema_version": _IMAGE_CACHE_SCHEMA_VERSION,
            "updated_at": None,
            "entries": {},
        }
    try:
        payload = read_json(path)
    except (OSError, ValueError):
        payload = {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _IMAGE_CACHE_SCHEMA_VERSION
        or not isinstance(payload.get("entries"), dict)
    ):
        payload = {}
    return {
        "schema_version": _IMAGE_CACHE_SCHEMA_VERSION,
        "updated_at": payload.get("updated_at"),
        "entries": dict(payload.get("entries", {})),
    }


def _write_image_cache(data_dir: Path, cache: dict[str, Any]) -> None:
    """把内存中的图片成功与失败记录原子写入当前数据根的缓存文件。
    输入：本次运行的数据根。
    - ``cache``：本地持久化缓存对象；包含状态、时间、响应元数据和可复用结果。
    """
    cache["schema_version"] = _IMAGE_CACHE_SCHEMA_VERSION
    cache["updated_at"] = _utc_iso()
    write_json(_image_cache_path(data_dir), cache)


def _safe_cached_image_path(data_dir: Path, value: object) -> Path | None:
    """把缓存相对路径限制在媒体目录并返回规范绝对路径。
    输出：未找到匹配项时返回 None。
    """
    relative = Path(str(value or "").replace("\\", "/"))
    if (
        not relative.parts
        or relative.is_absolute()
        or relative.parts[0] != "media"
        or ".." in relative.parts
    ):
        return None
    root = (data_dir / "media").resolve()
    candidate = (data_dir / relative).resolve()
    try:
        # 缓存记录属于不可信状态，命中前仍要阻止绝对路径和目录穿越。
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _cached_download(
    source_url: str,
    entry: object,
    data_dir: Path,
    config: MediaConfig,
) -> DownloadedImage | ImageDownloadError | None:
    """处理：校验缓存状态、时效、路径、大小和哈希后恢复图片结果。
    输入：本次运行的数据根、已校验的采集和输出配置。
    - ``source_url``：来源或图片的原始 URL；进入网络或索引前会执行相应规范化与安全检查。
    - ``entry``：图片缓存中的单条记录；校验状态、时效、路径、大小和哈希后才可复用。
    输出：通过公网、大小、格式和像素校验的本地图片记录，供报告渲染和远程投影复用。
    """
    if not isinstance(entry, dict):
        return None
    status = str(entry.get("status") or "")
    checked_at = _parse_cache_time(entry.get("checked_at"))
    now = _utc_now()
    if status == "failed":
        retry_after = _parse_cache_time(entry.get("retry_after"))
        if retry_after and now < retry_after:
            # 短期负缓存抑制反复请求坏链接，但到期后必须允许重新验证。
            return ImageDownloadError(
                "cached image failure; retry after " + retry_after.isoformat(timespec="seconds")
            )
        return None
    if status != "success" or checked_at is None:
        return None
    if now - checked_at > timedelta(hours=config.cache_success_ttl_hours):
        return None
    path = _safe_cached_image_path(data_dir, entry.get("local_path"))
    if path is None or not path.is_file():
        return None
    try:
        byte_size = int(entry["byte_size"])
        digest = str(entry["sha256"])
        if path.stat().st_size != byte_size:
            return None
        if sha256_file(path) != digest:
            return None
        return DownloadedImage(
            source_url=_serialized_http_url(source_url),
            resolved_url=_serialized_http_url(entry.get("resolved_url") or source_url),
            local_path=str(entry["local_path"]),
            content_type=str(entry["content_type"]),
            sha256=digest,
            byte_size=byte_size,
            width=int(entry["width"]),
            height=int(entry["height"]),
            reused=True,
            etag=str(entry.get("etag") or "") or None,
            last_modified=str(entry.get("last_modified") or "") or None,
        )
    except (KeyError, OSError, TypeError, ValueError):
        return None


def _cache_success(downloaded: DownloadedImage) -> dict[str, Any]:
    """把成功下载结果转换为可持久化缓存记录。
    输入：``downloaded``：已通过安全和格式校验的图片结果；包含最终 URL、路径、哈希和尺寸。
    输出：可复用的本地图片路径、文件摘要与条件请求所需的缓存标识。
    """
    return {
        "status": "success",
        "checked_at": _utc_iso(),
        "resolved_url": downloaded.resolved_url,
        "local_path": downloaded.local_path,
        "content_type": downloaded.content_type,
        "sha256": downloaded.sha256,
        "byte_size": downloaded.byte_size,
        "width": downloaded.width,
        "height": downloaded.height,
        "etag": downloaded.etag,
        "last_modified": downloaded.last_modified,
    }


def _cache_failure(exc: Exception, config: MediaConfig) -> dict[str, Any]:
    """把下载异常转换为带下次重试时间的负缓存记录。
    输入：已校验的采集和输出配置。
    - ``exc``：图片下载失败异常；提取错误文本并生成带重试时间的负缓存。
    输出：字段包括 checked_at、error、retry_after、status。
    """
    now = _utc_now()
    return {
        "status": "failed",
        "checked_at": _utc_iso(now),
        "retry_after": _utc_iso(
            now + timedelta(minutes=config.cache_failure_retry_minutes)
        ),
        "error": f"{type(exc).__name__}: {exc}",
    }


def _is_public_address(value: str) -> bool:
    """判断 IP 地址是否可由公网路由，排除本地和保留网段。"""
    address = ipaddress.ip_address(value)
    return address.is_global


def _resolve_system_addresses(hostname: str, port: int) -> tuple[str, ...]:
    """处理：通过系统解析器获取图片主机的全部连接地址。
    输入：
    - ``hostname``：图片 URL 的主机名；解析出的全部地址都必须可由公网路由。
    - ``port``：本地监控服务器监听端口；0 表示让操作系统分配可用端口。
    输出：“通过系统解析器获取图片主机的全部连接地址”得到的固定结构结果；
      各位置分别承载处理说明中的主结果和伴随状态。
    """
    try:
        return tuple(
            sorted(
                {
                    str(result[4][0])
                    for result in socket.getaddrinfo(
                        hostname,
                        port,
                        type=socket.SOCK_STREAM,
                    )
                }
            )
        )
    except OSError as exc:
        raise ImageDownloadError(
            f"image host {hostname!r} could not be resolved"
        ) from exc


def _is_proxy_fake_address(value: str) -> bool:
    """判断 IPv4 地址是否属于代理软件使用的 fake-IP 网段。"""
    address = ipaddress.ip_address(value)
    return isinstance(address, ipaddress.IPv4Address) and address in _PROXY_FAKE_IP_NETWORK


@lru_cache(maxsize=512)
def _resolve_public_dns_addresses(hostname: str) -> tuple[str, ...]:
    """处理：通过环境代理查询公共 DNS，确认本机未知或 fake-IP 域名的公网地址。
    输入：待确认域名；输出：解析到的 IP，供下载前的公网检查使用。
    """
    try:
        with httpx.Client(
            timeout=5.0,
            follow_redirects=False,
            trust_env=True,
        ) as client:
            for record_type, answer_type in (("A", 1), ("AAAA", 28)):
                response = client.get(
                    _PUBLIC_DNS_ENDPOINT,
                    params={"name": hostname, "type": record_type},
                    headers={
                        "Accept": "application/dns-json",
                        "User-Agent": _USER_AGENT,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("Status") != 0:
                    continue
                addresses: set[str] = set()
                for answer in payload.get("Answer", []):
                    if not isinstance(answer, dict) or answer.get("type") != answer_type:
                        continue
                    value = str(answer.get("data") or "")
                    try:
                        ipaddress.ip_address(value)
                    except ValueError:
                        continue
                    addresses.add(value)
                if addresses:
                    return tuple(sorted(addresses))
    except (httpx.HTTPError, TypeError, ValueError) as exc:
        raise ImageDownloadError(
            f"public DNS confirmation failed for image host {hostname!r}: "
            f"{type(exc).__name__}"
        ) from exc
    return ()


def assert_public_image_url(url: str) -> None:
    """拒绝凭证、非 HTTP 协议、异常端口和非公网图片主机。"""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ImageDownloadError("image URL must use public HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ImageDownloadError("image URL must not contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ImageDownloadError("image URL contains an invalid port") from exc
    if port not in {None, 80, 443}:
        raise ImageDownloadError("image URL must use port 80 or 443")
    if is_placeholder_image_url(url):
        raise ImageDownloadError("image URL is a known placeholder")

    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ImageDownloadError("image URL host is not public")
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None:
        if not literal_address.is_global:
            raise ImageDownloadError("image URL resolved to a non-public network address")
        return

    try:
        addresses = _resolve_system_addresses(
            hostname,
            port or (443 if parsed.scheme == "https" else 80),
        )
    except ImageDownloadError:
        addresses = ()
    if addresses and all(_is_public_address(address) for address in addresses):
        return
    if addresses and not all(_is_proxy_fake_address(address) for address in addresses):
        raise ImageDownloadError("image URL resolved to a non-public network address")

    # 本机 DNS 不可用或返回代理 fake-IP 时，改用公共 DNS 确认目标仍为公网。
    public_addresses = _resolve_public_dns_addresses(hostname)
    if public_addresses and all(_is_public_address(address) for address in public_addresses):
        return
    raise ImageDownloadError("image hostname public destination could not be confirmed")


def _inspect_raster(content: bytes, max_pixels: int) -> tuple[str, str, int, int]:
    """读取图片的实际格式与像素尺寸，返回内容类型、扩展名、宽和高。"""
    try:
        with Image.open(BytesIO(content)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            if image_format not in _ALLOWED_FORMATS:
                raise ImageDownloadError(
                    "image format must be JPEG, PNG, GIF, or WebP"
                )
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise ImageDownloadError(
                    f"image dimensions exceed the {max_pixels:,}-pixel safety limit"
                )
            image.verify()
        with Image.open(BytesIO(content)) as image:
            sample = image.convert("RGB")
            sample.thumbnail((64, 64))
            pixel_count = sample.width * sample.height
            statistics = ImageStat.Stat(sample)
            colors = sample.getcolors(maxcolors=pixel_count)
            dominant_ratio = (
                max(count for count, _color in colors) / pixel_count
                if colors and pixel_count
                else 0.0
            )
            channel_spans = [
                maximum - minimum for minimum, maximum in sample.getextrema()
            ]
            if max(statistics.stddev, default=0.0) < 1.0 or (
                dominant_ratio >= 0.985 and max(channel_spans, default=0) <= 24
            ):
                raise ImageDownloadError(
                    "downloaded image is a low-information placeholder"
                )
    except ImageDownloadError:
        raise
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
    ) as exc:
        raise ImageDownloadError("downloaded content is not a valid raster image") from exc
    content_type, extension = _ALLOWED_FORMATS[image_format]
    return content_type, extension, width, height


def _request_headers(referer: str | None) -> dict[str, str]:
    """构建图片请求头，并拒绝可注入换行的 Referer。
    输入：``referer``：可选来源页面 URL；通过换行和协议检查后才写入请求头。
    输出：字段包括 Accept、User-Agent。
    """
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "image/jpeg,image/png,image/gif,image/webp;q=0.9",
    }
    if (
        referer
        and "\r" not in referer
        and "\n" not in referer
        and urlsplit(referer).scheme in {"http", "https"}
    ):
        headers["Referer"] = referer
    return headers


def _serialized_http_url(url: str) -> str:
    """返回适合 JSON Schema 与远程发布器的 ASCII URI。
    输出：经过选择、规范化或安全处理的 URL 字符串，供后续访问或渲染使用。
    """
    try:
        return str(httpx.URL(url))
    except (httpx.InvalidURL, TypeError) as exc:
        raise ImageDownloadError("image URL could not be serialized as a URI") from exc


def download_image(
    source_url: str,
    data_dir: Path,
    config: MediaConfig,
    *,
    referer: str | None = None,
    max_bytes: int | None = None,
    client: httpx.Client | None = None,
    url_validator: Callable[[str], None] = assert_public_image_url,
) -> DownloadedImage:
    """处理：把单张不可信公网栅格图片下载到内容寻址的本地存储。
    输入：本次运行的数据根、已校验的采集和输出配置。
    - ``source_url``：报告索引提供的不可信公网图片 URL；每次重定向后都会重新执行公网校验。
    - ``referer``：可选来源页面 URL；通过换行和协议检查后才写入请求头。
    - ``max_bytes``：允许读取或下载的最大字节数；达到上限后停止或报错。
    - ``client``：已配置超时、重定向和连接池策略的 HTTP 客户端。
    - ``url_validator``：每次初始请求和重定向前调用的 URL 安全校验器；失败时必须阻止下载。
    输出：已验证并保存到内容寻址目录的图片记录；
      包含最终 URL、本地相对路径、哈希、字节数、尺寸和复用状态。
    """
    byte_limit = min(config.max_image_bytes, max_bytes or config.max_image_bytes)
    if byte_limit <= 0:
        raise ImageDownloadError("report image byte budget is exhausted")

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=config.request_timeout_seconds,
            follow_redirects=False,
            trust_env=True,
        )
    current_url = source_url
    deadline = time.monotonic() + config.request_timeout_seconds
    etag = None
    last_modified = None
    try:
        for redirect_count in range(config.max_redirects + 1):
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise ImageDownloadError("image request exceeded its total timeout")
            # 每一次重定向后的 URL 都重新校验，防止公网入口跳转到内网地址。
            url_validator(current_url)
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise ImageDownloadError("image request exceeded its total timeout")
            host = urlsplit(current_url).hostname or "unknown"
            try:
                with client.stream(
                    "GET",
                    current_url,
                    headers=_request_headers(referer),
                    timeout=remaining_seconds,
                ) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise ImageDownloadError(
                                f"image host {host!r} returned a redirect without a location"
                            )
                        if redirect_count >= config.max_redirects:
                            raise ImageDownloadError("image redirect limit was exceeded")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code >= 400:
                        raise ImageDownloadError(
                            f"image host {host!r} returned HTTP {response.status_code}"
                        )
                    etag = response.headers.get("etag")
                    last_modified = response.headers.get("last-modified")
                    raw_length = response.headers.get("content-length")
                    if raw_length:
                        try:
                            content_length = int(raw_length)
                        except ValueError:
                            content_length = None
                        if content_length is not None and content_length > byte_limit:
                            raise ImageDownloadError(
                                f"image exceeds the {byte_limit:,}-byte limit"
                            )
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        if time.monotonic() > deadline:
                            raise ImageDownloadError(
                                "image request exceeded its total timeout"
                            )
                        total += len(chunk)
                        if total > byte_limit:
                            raise ImageDownloadError(
                                f"image exceeds the {byte_limit:,}-byte limit"
                            )
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    break
            except ImageDownloadError:
                raise
            except httpx.HTTPError as exc:
                raise ImageDownloadError(
                    f"image request to host {host!r} failed: {type(exc).__name__}"
                ) from exc
        else:  # pragma: no cover - loop either breaks or raises
            raise ImageDownloadError("image redirect limit was exceeded")
    finally:
        if owns_client:
            client.close()

    if not content:
        raise ImageDownloadError("image response was empty")
    content_type, extension, width, height = _inspect_raster(
        content, config.max_image_pixels
    )
    digest = hashlib.sha256(content).hexdigest()
    # 内容寻址使相同图片跨报告复用，同时避免用不可信文件名落盘。
    relative_path = Path("media") / "images" / digest[:2] / f"{digest}{extension}"
    output_path = data_dir / relative_path
    reused = (
        output_path.is_file()
        and output_path.stat().st_size == len(content)
        and sha256_file(output_path) == digest
    )
    if not reused:
        write_bytes_atomic(output_path, content)
    return DownloadedImage(
        source_url=_serialized_http_url(source_url),
        resolved_url=_serialized_http_url(current_url),
        local_path=relative_path.as_posix(),
        content_type=content_type,
        sha256=digest,
        byte_size=len(content),
        width=width,
        height=height,
        reused=reused,
        etag=etag,
        last_modified=last_modified,
    )


def _report_briefs(report: dict[str, Any]) -> list[dict[str, Any]]:
    """从全部报告栏目展开结构化简报列表。"""
    return [
        brief
        for section in report.get("sections", [])
        if isinstance(section, dict)
        for brief in section.get("briefs", [])
        if isinstance(brief, dict)
    ]


_Input = TypeVar("_Input")
_Result = TypeVar("_Result")


def _domain_tasks(
    rows: list[tuple[str, _Input]],
    run: Callable[[str, _Input], _Result],
    pool: ThreadPoolExecutor,
    config: MediaConfig,
) -> Iterator[tuple[str, Future[_Result]]]:
    """处理：按域名轮转提交当前可开始的 HTTP 任务。
    输入：以 URL 为首项的待请求列表、执行函数和媒体并发配置。
    输出：已完成的请求，交由页面抽取或图片下载分别处理结果与错误。
    """
    queues: dict[str, deque[tuple[str, _Input]]] = defaultdict(deque)
    for url, argument in rows:
        queues[(urlsplit(url).hostname or "unknown").casefold()].append((url, argument))
    domains = deque(queues)
    active: dict[str, int] = defaultdict(int)
    pending: dict[Future[_Result], tuple[str, str]] = {}
    while domains or pending:
        while len(pending) < config.global_concurrency:
            for _ in range(len(domains)):
                domain = domains.popleft()
                queue = queues[domain]
                if active[domain] < config.per_domain_concurrency:
                    url, argument = queue.popleft()
                    pending[pool.submit(run, url, argument)] = (url, domain)
                    active[domain] += 1
                    if queue:
                        domains.append(domain)
                    break
                domains.append(domain)
            else:
                break
        for future in wait(pending, return_when=FIRST_COMPLETED).done:
            url, domain = pending.pop(future)
            active[domain] -= 1
            yield url, future



def _download_image_batch(
    rows: list[tuple[str, str | None]],
    data_dir: Path,
    config: MediaConfig,
    max_bytes: int,
    downloader: Callable[..., DownloadedImage],
    *,
    resources: ExitStack | None = None,
    shared: dict[str, Any] | None = None,
) -> dict[str, DownloadedImage | Exception]:
    """处理：使用共享连接池和同域限制下载一个优先级批次。
    输入：本次运行的数据根、已校验的采集和输出配置。
    - ``rows``：同一优先级的图片候选二元组；每项依次提供公网图片 URL 和可选来源页 Referer。
    - ``max_bytes``：允许读取或下载的最大字节数；达到上限后停止或报错。
    - ``downloader``：图片下载函数；接收候选 URL、来源页和安全预算，返回已验证的本地图片记录。
    输出：通过公网、大小、格式和像素校验的本地图片记录，供报告渲染和远程投影复用。
    """
    if not rows:
        return {}
    if downloader is not download_image:
        results: dict[str, DownloadedImage | Exception] = {}
        for source_url, referer in rows:
            try:
                results[source_url] = downloader(
                    source_url,
                    data_dir,
                    config,
                    referer=referer,
                    max_bytes=max_bytes,
                )
            except (ImageDownloadError, OSError) as exc:
                results[source_url] = exc
        return results

    if resources is None or shared is None:
        with ExitStack() as stack:
            return _download_image_batch(
                rows, data_dir, config, max_bytes, downloader, resources=stack, shared={},
            )
    if "client" not in shared:
        shared["client"] = resources.enter_context(httpx.Client(
            timeout=config.request_timeout_seconds, follow_redirects=False, trust_env=True,
        ))
        shared["executor"] = resources.enter_context(ThreadPoolExecutor(
            max_workers=config.global_concurrency, thread_name_prefix="daily-intel-image",
        ))
    def download(source_url: str, referer: str | None) -> DownloadedImage:
        """处理：通过批次共享连接下载单张图片。
        输入：调度器选中的图片 URL 和来源页地址。
        输出：通过解码检查的本地图片及其缓存信息。
        """
        return downloader(source_url, data_dir, config, referer=referer,
                          max_bytes=max_bytes, client=shared["client"])

    results = {}
    for source_url, future in _domain_tasks(rows, download, shared["executor"], config):
        try:
            results[source_url] = future.result()
        except (ImageDownloadError, OSError) as exc:
            results[source_url] = exc
    return results


def _indexed_image_candidates(indexed: dict[str, Any]) -> list[dict]:
    """合并索引主图片与元数据候选并规范化 URL。
    输入：``indexed``：权威来源索引中与当前 item_id 对应的条目记录。
    输出：保留原站图注和尺寸的有序记录，供预取和报告附件共用。
    """
    values: list[object] = [indexed.get("image_url")]
    direct_candidates = indexed.get("image_candidates")
    if isinstance(direct_candidates, list):
        values.extend(direct_candidates)
    metadata = indexed.get("metadata")
    if isinstance(metadata, dict):
        metadata_candidates = metadata.get("image_candidates")
        if isinstance(metadata_candidates, list):
            values.extend(metadata_candidates)
    details = {
        row["url"]: row for row in (metadata or {}).get("image_candidate_details", [])
    }
    images = [
        {**details.get(url, {}), "url": url}
        for candidate in normalize_image_candidates(values)
        for url in image_resolution_candidates(candidate)
    ]
    groups = image_variant_groups(images)

    def signed_family(group: list[dict]) -> tuple | None:
        """处理：比较 Guardian 已给出的同原图尺寸，不改写签名或裁切参数。
        输入：保留完整 URL 的候选组。
        输出：相同路径及裁切共享排序族，其他发布者保持原顺序。
        """
        parsed = urlsplit(group[0]["url"])
        if parsed.hostname != "i.guim.co.uk":
            return None
        return (parsed.scheme, parsed.netloc, parsed.path,
                tuple((key, value) for key, value in parse_qsl(parsed.query)
                      if key not in {"width", "w", "height", "h", "dpr", "s",
                                     "quality", "q", "auto", "format"}))

    families = {}
    family_keys = [signed_family(group) for group in groups]
    for group, family in zip(groups, family_keys, strict=True):
        if family is not None:
            families.setdefault(family, []).append(group)
    ordered = {key: iter(sorted(rows, key=lambda group: _image_pixels(group[0]), reverse=True))
               for key, rows in families.items()}
    # URL 仍各自保留有效签名；只调整同图尺寸的尝试顺序，失败后继续回退。
    return list(chain.from_iterable(
        next(ordered[family]) if family is not None else group
        for group, family in zip(groups, family_keys, strict=True)
    ))


def materialize_report_images(
    report: dict[str, Any],
    index: dict[str, Any],
    data_dir: Path,
    config: MediaConfig,
    *,
    downloader: Callable[..., DownloadedImage] = download_image,
    preserved_images: dict[str, dict | None] | None = None,
) -> list[str]:
    """处理：在整轮图片处理期间复用连接池，结束或失败时统一释放资源。
    输入：已编译报告、权威索引、数据根、图片预算及可注入下载器。
    输出：按原优先级附图后的报告和显式警告；全缓存命中时不创建网络资源。
    """
    with ExitStack() as resources:
        return _materialize_report_images(
            report, index, data_dir, config, downloader=downloader, resources=resources,
            preserved_images=preserved_images,
        )


def _indexed_image_caption(indexed: dict[str, Any], image_url: str) -> str:
    """处理：按选中图片 URL 读取当前新闻的原站图注。
    输入：当前新闻索引及实际下载成功的候选 URL。
    输出：报告图片 caption；缺失时返回空串，不借用标题或缓存说明。
    """
    details = (indexed.get("metadata") or {}).get("image_candidate_details", [])
    return next(
        (str(entry.get("caption") or "") for entry in details if entry["url"] == image_url),
        "",
    )


def _image_variant_urls(candidates: Iterable[dict], cache_entries: dict) -> dict[str, list[str]]:
    """处理：合并当前候选与已有高清缓存，供预取和最终附件共用尺寸选择。
    输入：当前索引条目及媒体缓存记录。
    输出：每个候选对应的高清优先地址列表，保留失败回退顺序。
    """
    details = {}
    for row in candidates:
        details.setdefault(row["url"], row)
    selected_keys = {image_variant_key(url) for url in details}
    for url, entry in cache_entries.items():
        if (isinstance(entry, dict) and entry.get("status") == "success"
                and image_variant_key(url) in selected_keys):
            details[url] = {**details.get(url, {}), "url": url,
                            "width": entry.get("width"), "height": entry.get("height")}
    variants = {}
    for group in image_variant_groups(list(details.values())):
        urls = list(dict.fromkeys(row["url"] for row in group))
        for url in urls:
            variants[url] = urls
    return variants


def _materialize_report_images(
    report: dict[str, Any], index: dict[str, Any], data_dir: Path, config: MediaConfig,
    *, downloader: Callable[..., DownloadedImage], resources: ExitStack,
    preserved_images: dict[str, dict | None] | None = None,
) -> list[str]:
    """处理：将权威索引图片绑定到报告简报并持久化本地副本。
    输入：本次运行的数据根、已校验的采集和输出配置。
    - ``report``：已编译报告对象；函数只为与权威索引匹配的简报附加本地图片元数据。
    - ``index``：权威来源索引；提供 item_id 对应的来源页、图片候选和来源身份。
    - ``downloader``：可注入的图片下载函数；生产使用安全下载器，测试可替换为确定性实现。
    输出：未能附图或降级时的警告列表；report 会就地获得通过预算和安全校验的本地图片元数据。
    """
    briefs = _report_briefs(report)
    preserved = {}
    without_image = set()
    for brief in briefs:
        brief.pop("image", None)
        item_id = str(brief.get("item_id"))
        image = (preserved_images or {}).get(item_id)
        if preserved_images is not None and item_id in preserved_images and image is None:
            without_image.add(item_id)
        if image:
            path = _safe_cached_image_path(data_dir, image.get("local_path"))
            if path is not None and path.is_file():
                content = path.read_bytes()
                if (len(content) == image["byte_size"]
                        and hashlib.sha256(content).hexdigest() == image["sha256"]):
                    # 文字修订沿用已发布附件的原图、裁切和图注，缺失或失效才重新选图。
                    preserved[str(brief["item_id"])] = image
    indexed_items = {
        str(item.get("item_id")): item
        for item in index.get("items", [])
        if isinstance(item, dict) and item.get("item_id")
    }
    candidates: list[
        tuple[int, dict[str, Any], dict[str, Any], list[str]]
    ] = []
    images_by_item = {}
    for order, brief in enumerate(briefs):
        item_id = str(brief.get("item_id"))
        if item_id in without_image:
            continue
        indexed = indexed_items.get(item_id)
        if not indexed:
            continue
        if item_id in preserved:
            image_candidates = ["preserved:" + item_id]
        else:
            if item_id not in images_by_item:
                images_by_item[item_id] = _indexed_image_candidates(indexed)
            image_candidates = [row["url"] for row in images_by_item[item_id]]
        if not image_candidates:
            continue
        candidates.append((order, brief, indexed, image_candidates))
    candidates.sort(
        key=lambda row: (
            -int(row[1].get("importance", 0)),
            int(row[1].get("source_rank", 1_000_000)),
            row[0],
        )
    )

    metrics = {
        "candidates": len(candidates),
        "attached": 0,
        "unique_files": 0,
        "reused_files": 0,
        "failed": 0,
        "skipped_budget": 0,
        "total_bytes": 0,
    }
    report["media_metrics"] = metrics
    if preserved_images is not None:
        metrics["preserved_without_image"] = len(without_image)
    if not config.enabled or config.max_images_per_report == 0:
        metrics["skipped_budget"] = len(candidates)
        return []

    warnings: list[str] = []
    unique_digests: set[str] = set()
    # 已发布附件按条目独立复用，继续经过原有数量和字节预算分配，不进入 URL 变体重选。
    resolved_by_url: dict[str, DownloadedImage | Exception] = {
        "preserved:" + item_id: DownloadedImage(**{key: image[key] for key in (
            "source_url", "resolved_url", "local_path", "content_type", "sha256", "byte_size",
            "width", "height")}, reused=True)
        for item_id, image in preserved.items()}
    cache_enabled = downloader is download_image
    cache = _load_image_cache(data_dir) if cache_enabled else {"entries": {}}
    cache_entries = cache["entries"]
    for _, brief, indexed, _ in candidates:
        item_id = str(brief["item_id"])
        if item_id not in images_by_item:
            images_by_item[item_id] = _indexed_image_candidates(indexed)
    variant_urls = _image_variant_urls(
        (row for _, brief, _, _ in candidates for row in images_by_item[str(brief["item_id"])]),
        cache_entries,
    )
    cache_warning_emitted = False
    shared: dict[str, Any] = {}

    def resolve_exact_rows(
        rows: list[tuple[str, str | None]],
        max_bytes: int,
    ) -> None:
        """复用图片缓存并批量下载尚未解析的候选 URL，随后写入检查点。
        输入：
        - ``rows``：当前优先级的图片候选二元组；每项是 image_url 与可选 referer，
          URL 会先查缓存再下载。
        - ``max_bytes``：允许读取或下载的最大字节数；达到上限后停止或报错。
        """
        nonlocal cache_warning_emitted
        batch: list[tuple[str, str | None]] = []
        batch_urls: set[str] = set()
        for image_url, referer in rows:
            if image_url in resolved_by_url or image_url in batch_urls:
                continue
            if cache_enabled:
                try:
                    cache_key = _serialized_http_url(image_url)
                except ImageDownloadError as exc:
                    resolved_by_url[image_url] = exc
                    continue
                cached = _cached_download(
                    image_url,
                    cache_entries.get(cache_key),
                    data_dir,
                    config,
                )
                if cached is not None:
                    # 成功缓存和仍在退避期的失败缓存都视为已解析，避免重复网络工作。
                    resolved_by_url[image_url] = cached
                    continue
            batch.append((image_url, referer))
            batch_urls.add(image_url)
        if not batch:
            return

        batch_results = _download_image_batch(
            batch,
            data_dir,
            config,
            max_bytes,
            downloader,
            resources=resources,
            shared=shared,
        )
        resolved_by_url.update(batch_results)
        if not cache_enabled:
            return
        for image_url, result in batch_results.items():
            cache_key = _serialized_http_url(image_url)
            cache_entries[cache_key] = (
                _cache_success(result)
                if isinstance(result, DownloadedImage)
                else _cache_failure(result, config)
            )
        try:
            # 每个批次后落盘检查点；进程中断也能复用已经完成的下载。
            _write_image_cache(data_dir, cache)
        except OSError as exc:
            if not cache_warning_emitted:
                warnings.append(
                    "image cache checkpoint failed: "
                    f"{type(exc).__name__}: {exc}"
                )
                cache_warning_emitted = True

    def resolve_rows(rows: list[tuple[str, str | None]], max_bytes: int) -> None:
        """处理：同一原图只尝试最高尺寸，失败后按组降级并共享成功缓存。
        输入：当前新闻候选 URL、Referer 与剩余预算。
        输出：全部同图候选指向已成功取得的最高版本，避免跨新闻重复下载缩略图。
        """
        pending = {}
        for url, referer in rows:
            urls = variant_urls.get(url, [url])
            pending.setdefault(urls[0], (urls, referer))
        while pending:
            attempts = []
            for key, (urls, referer) in list(pending.items()):
                success = next((resolved_by_url[url] for url in urls
                                if isinstance(resolved_by_url.get(url), DownloadedImage)), None)
                if success is not None:
                    for url in urls:
                        resolved_by_url[url] = success
                    del pending[key]
                    continue
                unresolved = next((url for url in urls if url not in resolved_by_url), None)
                if unresolved is None:
                    del pending[key]
                else:
                    attempts.append((unresolved, referer))
            if attempts:
                resolve_exact_rows(attempts, max_bytes)

    cursor = 0
    prefetched_until = 0
    while cursor < len(candidates):
        if int(metrics["attached"]) >= config.max_images_per_report:
            metrics["skipped_budget"] += len(candidates) - cursor
            break
        remaining_bytes = config.max_total_bytes - int(metrics["total_bytes"])
        if remaining_bytes <= 0:
            metrics["skipped_budget"] += len(candidates) - cursor
            break

        if cursor >= prefetched_until:
            # 完整消费已预取的窗口，避免滑动一位后反复启动单张下载。
            batch_limit = min(
                config.global_concurrency if cache_enabled else 1,
                config.max_images_per_report - int(metrics["attached"]),
            )
            prefetched_until = min(len(candidates), cursor + batch_limit)
            primary_rows = [
                (image_candidates[0], str(indexed.get("url") or "") or None)
                for _order, _brief, indexed, image_candidates
                in candidates[cursor:prefetched_until]
            ]
            resolve_rows(primary_rows, min(config.max_image_bytes, remaining_bytes))

        _order, brief, indexed, image_candidates = candidates[cursor]
        cursor += 1
        item_id = str(brief.get("item_id") or "")
        downloaded: DownloadedImage | None = None
        failures: list[Exception] = []
        referer = str(indexed.get("url") or "") or None
        for image_url in image_candidates:
            if image_url not in resolved_by_url:
                remaining_bytes = config.max_total_bytes - int(metrics["total_bytes"])
                resolve_rows(
                    [(image_url, referer)],
                    min(config.max_image_bytes, remaining_bytes),
                )
            result = resolved_by_url.get(image_url)
            if isinstance(result, DownloadedImage):
                downloaded = result
                break
            failures.append(
                result
                if isinstance(result, Exception)
                else ImageDownloadError("image download did not produce a result")
            )
        if downloaded is None:
            exc = failures[-1]
            metrics["failed"] += 1
            warnings.append(
                f"image omitted for item_id={item_id!r} after "
                f"{len(failures)} candidate(s): {type(exc).__name__}: {exc}"
            )
            continue

        if downloaded.sha256 not in unique_digests:
            remaining_bytes = config.max_total_bytes - int(metrics["total_bytes"])
            if downloaded.byte_size > remaining_bytes:
                metrics["skipped_budget"] += 1
                continue
            unique_digests.add(downloaded.sha256)
            metrics["unique_files"] += 1
            metrics["total_bytes"] += downloaded.byte_size
            if downloaded.reused:
                metrics["reused_files"] += 1
        source = brief.get("primary_source")
        credit = (
            str(source.get("name"))
            if isinstance(source, dict) and source.get("name")
            else str(indexed.get("source_name") or indexed.get("source_id") or "原始来源")
        )
        brief["image"] = dict(preserved[item_id]) if item_id in preserved else {
            "source_url": downloaded.source_url,
            "resolved_url": downloaded.resolved_url,
            "local_path": downloaded.local_path,
            "content_type": downloaded.content_type,
            "sha256": downloaded.sha256,
            "byte_size": downloaded.byte_size,
            "width": downloaded.width,
            "height": downloaded.height,
            "caption": _indexed_image_caption(indexed, image_url),
            "credit": credit,
        }
        metrics["attached"] += 1
    return warnings


def prefetch_index_images(
    index: dict[str, Any],
    item_ids: list[str],
    data_dir: Path,
    config: MediaConfig,
) -> dict[str, Any]:
    """处理：独立预取每条新闻的首个可用高清图，并按域轮转填充下载槽位。
    输入：当前索引、选定条目、媒体缓存及独立的新下载预算。
    输出：缓存就绪条数、实际下载字节和失败统计；最终报告仍按自己的附件预算选图。
    """
    started = time.perf_counter()
    wanted = set(map(str, item_ids))
    items = [item for item in index.get("items", []) if str(item.get("item_id")) in wanted]
    cache = _load_image_cache(data_dir)
    candidates = [_indexed_image_candidates(item) for item in items]
    variants = _image_variant_urls(chain.from_iterable(candidates), cache["entries"])
    pending = []
    for item, images in zip(items, candidates, strict=True):
        urls = list(dict.fromkeys(url for image in images for url in variants[image["url"]]))
        if urls:
            pending.append({"item": item, "urls": deque(urls), "error": None,
                            "budget_blocked": False})
    metrics = {"candidates": len(pending), "ready": 0, "downloaded_files": 0,
               "reused_items": 0, "failed": 0, "skipped_budget": 0, "downloaded_bytes": 0,
               "download_budget_bytes": config.prefetch_max_total_bytes, "host_deferred_urls": 0}
    warnings = []
    if not config.enabled:
        metrics["skipped_budget"] = len(pending)
        pending = []
    resolved: dict[str, DownloadedImage | Exception | None] = {}
    downloaded_urls = set()
    budget_exhausted = False
    transport_failures: dict[str, int] = {}
    successful_hosts = set()
    deferred_hosts = set()

    def defer_host_url(url: str) -> bool:
        """处理：当前宿主重复传输超时后暂缓同域新请求，其他来源继续处理。
        输入：尚未发出的候选 URL 和本轮网络结果。
        输出：暂缓时保存可重试负缓存，不改变新闻或来源采集状态。
        """
        host = urlsplit(url).netloc
        if host not in deferred_hosts:
            return False
        if resolved.get(url) is None:
            value = ImageDownloadError(
                f"image host {host!r} temporarily deferred after repeated transport failures",
            )
            resolved[url] = value
            cache["entries"][_serialized_http_url(url)] = _cache_failure(value, config)
            metrics["host_deferred_urls"] += 1
        return True

    with ExitStack() as resources:
        shared: dict[str, Any] = {}
        while pending:
            rows = {}
            retry = []
            for task in pending:
                while task["urls"]:
                    url = task["urls"][0]
                    if url not in resolved:
                        resolved[url] = _cached_download(
                            url, cache["entries"].get(_serialized_http_url(url)), data_dir, config,
                        )
                    if resolved[url] is None:
                        defer_host_url(url)
                    value = resolved[url]
                    if isinstance(value, DownloadedImage):
                        metrics["ready"] += 1
                        metrics["reused_items"] += int(url not in downloaded_urls)
                        break
                    if isinstance(value, Exception):
                        task["error"] = value
                        task["urls"].popleft()
                    elif budget_exhausted:
                        task["budget_blocked"] = True
                        task["urls"].popleft()
                    else:
                        rows.setdefault(url, str(task["item"].get("url") or "") or None)
                        retry.append(task)
                        break
                else:
                    if task["budget_blocked"]:
                        metrics["skipped_budget"] += 1
                    else:
                        metrics["failed"] += 1
                        warnings.append(f"image prefetch failed for {task['item']['item_id']}: "
                                        f"{task['error']}")
            pending = retry
            # 同域任务轮流进入批次，避免一个来源占满线程后只剩域内两个请求活动。
            domains: dict[str, deque] = {}
            for url, referer in rows.items():
                domains.setdefault(urlsplit(url).netloc, deque()).append((url, referer))
            scheduled = deque()
            while any(domains.values()):
                for queue in domains.values():
                    if queue:
                        scheduled.append(queue.popleft())
            while scheduled:
                remaining = config.prefetch_max_total_bytes - metrics["downloaded_bytes"]
                # 线程池持续补位；按最大单图字节预留本批预算，避免慢请求形成逐窗等待。
                count = min(len(scheduled), remaining // config.max_image_bytes)
                if count == 0:
                    budget_exhausted = True
                    break
                batch = []
                while scheduled and len(batch) < count:
                    row = scheduled.popleft()
                    if not defer_host_url(row[0]):
                        batch.append(row)
                if not batch:
                    continue
                results = _download_image_batch(
                    batch, data_dir, config, config.max_image_bytes, download_image,
                    resources=resources, shared=shared,
                )
                for url, _referer in batch:
                    value = results.get(
                        url, ImageDownloadError("image download produced no result"),
                    )
                    resolved[url] = value
                    host = urlsplit(url).netloc
                    key = _serialized_http_url(url)
                    if isinstance(value, DownloadedImage):
                        metrics["downloaded_files"] += 1
                        metrics["downloaded_bytes"] += value.byte_size
                        downloaded_urls.add(url)
                        cache["entries"][key] = _cache_success(value)
                        successful_hosts.add(host)
                    else:
                        cache["entries"][key] = _cache_failure(value, config)
                        if any(reason in str(value) for reason in (
                            "ReadTimeout", "ConnectTimeout", "ConnectError", "ReadError",
                            "WriteTimeout", "public DNS confirmation failed", "SSL",
                            "image request exceeded its total timeout",
                        )):
                            transport_failures[host] = transport_failures.get(host, 0) + 1
                deferred_hosts.update(host for host, count in transport_failures.items()
                                      if count >= 2 and host not in successful_hosts)
                _write_image_cache(data_dir, cache)
    _write_image_cache(data_dir, cache)
    return {
        **metrics,
        "deferred_hosts": sorted(deferred_hosts),
        "transport_failures_by_host": transport_failures,
        "requested_item_count": len(item_ids),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "warnings": warnings,
    }
