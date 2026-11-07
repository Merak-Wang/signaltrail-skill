from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .config import AppConfig, project_root
from .edition_reader import edition_artifact_path, list_editions, read_edition, read_edition_event
from .events import get_event, get_follows, list_events, set_follow
from .monitor import refresh_monitor

_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def _asset_dir() -> Path:
    """处理：返回本地监控页面静态资源目录。
    输入：
    - 无显式业务参数：不接收参数；根据当前模块位置定位仓库内受控的 assets 目录。
    输出：指向“返回本地监控页面静态资源目录”所生成、定位或确认产物的本地路径。
    """
    return project_root() / "assets" / "monitor"


def _json_bytes(payload: object) -> bytes:
    """处理：把对象编码为可直接返回的 UTF-8 JSON 字节。
    输入：
    - ``payload``：上游传入的结构化对象；函数只读取处理说明列出的受支持字段。
    输出：受大小边界约束的字节内容，可直接写入文件或 HTTP 响应。
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _handler_factory(
    data_dir: Path,
    assets: Path,
    *,
    quiet: bool,
) -> type[BaseHTTPRequestHandler]:
    """处理：创建绑定数据目录与配置的本地监控 HTTP 处理器。
    输入：
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``assets``：监控 Web UI 的静态资源目录；HTTP 处理器只允许从该根目录读取。
    - ``quiet``：是否抑制正常的本地监控 HTTP 访问日志。
    输出：封装“创建绑定数据目录与配置的本地监控 HTTP 处理器”业务结果的 ``type[BaseHTTPRequestHan
      dler]`` 对象；调用方据此继续相邻阶段或识别无结果状态。
    """

    class MonitorHandler(BaseHTTPRequestHandler):
        """处理：路由本地监控的静态资产、快照、健康状态和刷新请求。
        输入：
        - 无显式业务参数：不声明额外构造字段；该定义以 ``BaseHTTPRequestHandler`` 为基础，
          通过类成员承担“路由本地监控的静态资产、快照、健康状态和刷新请求”职责。
        输出：构造后的 ``MonitorHandler`` 实例或枚举定义；其字段和方法共同承担上述职责。
        """

        server_version = "DailyIntelligenceMonitor/2.0"

        def _send(
            self,
            content: bytes,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            """处理：写入状态码、响应头和字节正文。
            输入：
            - ``content``：待编码、解析或写入的原始内容；边界和可信级别由当前函数说明。
            - ``content_type``：HTTP 内容类型或待上传文件 MIME 类型；用于解析、校验和响应头。
            - ``status``：当前操作或来源状态；值必须属于对应的显式状态模型。
            输出：不返回新数据；完成“写入状态码、响应头和字节正文”，
              副作用限于该处理声明的受控对象或产物。
            """
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                (
                    "default-src 'self'; img-src 'self' https: data:; "
                    "style-src 'self'; script-src 'self'; connect-src 'self'; "
                    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
                ),
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(content)

        def _send_json(
            self,
            payload: object,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            """处理：把对象编码为 JSON 后发送 HTTP 响应。
            输入：
            - ``payload``：上游传入的结构化对象；函数只读取处理说明列出的受支持字段。
            - ``status``：当前操作或来源状态；值必须属于对应的显式状态模型。
            输出：不返回新数据；完成“把对象编码为 JSON 后发送 HTTP 响应”，
              副作用限于该处理声明的受控对象或产物。
            """
            self._send(_json_bytes(payload), _CONTENT_TYPES[".json"], status)

        def _serve_file(self, path: Path) -> None:
            """处理：校验静态资源路径后读取文件并返回正确内容类型。
            输入：
            - ``path``：当前函数要读取、校验或写入的本地文件路径。
            输出：不返回新数据；完成“校验静态资源路径后读取文件并返回正确内容类型”，
              副作用限于该处理声明的受控对象或产物。
            """
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(assets.resolve())
            except (FileNotFoundError, ValueError):
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            self._send(
                resolved.read_bytes(),
                _CONTENT_TYPES.get(resolved.suffix.lower(), "application/octet-stream"),
            )

        def do_HEAD(self) -> None:  # noqa: N802
            """处理：复用监控 GET 路由校验并仅返回状态与响应头，不发送正文。
            输入：
            - 无显式业务参数：不接收额外业务参数；
              从当前实例读取“复用监控 GET 路由校验并仅返回状态与响应头，不发送正文”所需状态；
              实现会明确读取属性 do_GET。
            输出：不返回新数据；完成“复用监控 GET 路由校验并仅返回状态与响应头，不发送正文”，
              副作用限于该处理声明的受控对象或产物。
            """
            self.do_GET()

        def _serve_artifact(self, relative: str) -> None:
            """处理：流式读取已有日报及其本地媒体文件。
            输入：相对资料根的产物路径；仅开放报告与媒体目录。
            输出：可阅读或播放的原文件，视频支持字节区间请求。
            """
            path = edition_artifact_path(data_dir, unquote(relative))
            if path is None:
                self._send_json({"error": "artifact_not_found"}, HTTPStatus.NOT_FOUND)
                return
            size = path.stat().st_size
            start, end = 0, size - 1
            requested = self.headers.get("Range", "")
            if requested.startswith("bytes="):
                left, _, right = requested[6:].partition("-")
                start = int(left) if left.isdigit() else 0
                end = min(int(right), size - 1) if right.isdigit() else size - 1
                if not left and right.isdigit():
                    start, end = max(0, size - int(right)), size - 1
            if start > end or start >= size:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(HTTPStatus.PARTIAL_CONTENT if requested else HTTPStatus.OK)
            self.send_header(
                "Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self' https: data:; style-src 'self' 'unsafe-inline' https:; "
                "script-src 'self' 'unsafe-inline'; frame-ancestors 'self'; object-src 'none'",
            )
            self.end_headers()
            if self.command != "HEAD":
                with path.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining and (chunk := stream.read(min(1024 * 1024, remaining))):
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

        def do_GET(self) -> None:  # noqa: N802
            """处理：按受控路由返回监控快照、健康状态或白名单内的静态资源。
            输入：
            - 无显式业务参数：不接收额外业务参数；
              从当前实例读取“按受控路由返回监控快照、健康状态或白名单内的静态资源”所需状态；
              实现会明确读取属性 _send_json、_serve_file、path。
            输出：不返回新数据；完成“按受控路由返回监控快照、健康状态或白名单内的静态资源”，
              副作用限于该处理声明的受控对象或产物。
            """
            route = self.path.split("?", 1)[0]
            if route.startswith("/files/"):
                self._serve_artifact(route.removeprefix("/files/"))
                return
            if route == "/api/editions":
                self._send_json(list_editions(data_dir))
                return
            if route == "/api/edition":
                query = parse_qs(urlsplit(self.path).query)
                filters = {
                    key: query.get(key, [""])[0]
                    for key in ("date", "edition", "revision", "language")
                }
                self._send_json(read_edition(data_dir, **filters))
                return
            if route in {"/", "/index.html"} or route.startswith("/events/"):
                self._serve_file(assets / "index.html")
                return
            if route == "/app.js":
                self._serve_file(assets / "app.js")
                return
            if route == "/styles.css":
                self._serve_file(assets / "styles.css")
                return
            if route == "/api/events":
                query = parse_qs(urlsplit(self.path).query)
                filters = {key: query.get(key, [""])[0] for key in ("category", "source", "q")}
                try:
                    limit = int(query.get("limit", ["60"])[0])
                    offset = int(query.get("offset", ["0"])[0])
                except ValueError:
                    self._send_json({"error": "invalid_pagination"}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(
                    list_events(
                        data_dir,
                        sort=query.get("sort", ["latest"])[0],
                        following=query.get("following", [""])[0] == "1",
                        **filters,
                        limit=limit,
                        offset=offset,
                    )
                )
                return
            if route.startswith("/api/events/"):
                query = parse_qs(urlsplit(self.path).query)
                if query.get("report_id"):
                    detail = read_edition_event(
                        data_dir,
                        query["report_id"][0],
                        query.get("report_event_id", [unquote(route.removeprefix("/api/events/"))])[
                            0
                        ],
                        language=query.get("language", [""])[0],
                    )
                else:
                    detail = get_event(data_dir, unquote(route.removeprefix("/api/events/")))
                self._send_json(
                    detail or {"error": "event_not_found"},
                    HTTPStatus.OK if detail else HTTPStatus.NOT_FOUND,
                )
                return
            if route == "/api/follows":
                self._send_json(get_follows(data_dir))
                return
            if route == "/api/snapshot":
                snapshot = data_dir / "monitor" / "snapshot.json"
                if not snapshot.exists():
                    self._send_json(
                        {
                            "error": "snapshot_not_found",
                            "message": "请先运行 signaltrail refresh-monitor",
                        },
                        HTTPStatus.NOT_FOUND,
                    )
                    return
                try:
                    payload = json.loads(snapshot.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    self._send_json(
                        {"error": "snapshot_invalid", "message": str(exc)},
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(payload)
                return
            if route == "/api/health":
                self._send_json(
                    {
                        "status": "ok",
                        "read_only": False,
                    }
                )
                return
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

        def _discard_short_body(self) -> None:
            """处理：拒绝跨源请求时限时消耗已发送的短正文，避免 Windows 关闭连接时复位。
            输入：请求头声明的长度与当前连接；分块、超限和无效长度不读取。
            输出：最多丢弃 8192 字节，正文不解析、不参与业务写入。
            """
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                return
            if self.headers.get("Transfer-Encoding") or not 0 < length <= 8192:
                return
            timeout = self.connection.gettimeout()
            self.connection.settimeout(0.25)
            try:
                self.rfile.read(length)
            except OSError:
                pass
            finally:
                self.connection.settimeout(timeout)

        def do_POST(self) -> None:  # noqa: N802
            """处理：接受同源页面的关注变更。
            输入：关注类型、目标与开关。
            输出：保存后的关注列表。
            """
            origin = self.headers.get("Origin")
            if (origin and urlsplit(origin).netloc != self.headers.get("Host")) or self.headers.get(
                "Sec-Fetch-Site"
            ) == "cross-site":
                self._discard_short_body()
                self._send_json({"error": "origin_not_allowed"}, HTTPStatus.FORBIDDEN)
                return
            route = urlsplit(self.path).path
            if route != "/api/follows":
                self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 8192:
                    raise ValueError("请求大小不正确")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("请求必须为JSON对象")
                if type(payload.get("following")) is not bool:
                    raise ValueError("关注开关必须为布尔值")
                result = set_follow(
                    data_dir, payload.get("kind"), payload.get("target"), payload["following"]
                )
            except (ValueError, TypeError) as exc:
                self._send_json(
                    {"error": "invalid_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST
                )
                return
            self._send_json(result)

        def log_message(self, message_format: str, *args: Any) -> None:
            """处理：按监控服务的日志格式记录请求。
            输入：
            - ``message_format``：BaseHTTPRequestHandler 提供的日志格式字符串。
            - ``*args``：HTTP 处理器用于填充日志格式字符串的参数。
            输出：不返回新数据；完成“按监控服务的日志格式记录请求”，
              副作用限于该处理声明的受控对象或产物。
            """
            if not quiet:
                super().log_message(message_format, *args)

    return MonitorHandler


def create_monitor_server(
    data_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    """处理：创建绑定日报、新闻档案与关注入口的 HTTP 服务。
    输入：
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``host``：本地监控服务器绑定的主机地址；远程地址需要显式授权。
    - ``port``：本地监控服务器监听端口；0 表示让操作系统分配可用端口。
    - ``quiet``：是否抑制正常的本地监控 HTTP 访问日志。
    输出：封装“创建只监听本地地址并绑定监控快照的线程式 HTTP 服务”业务结果的 ``ThreadingHTTPServ
      er`` 对象；调用方据此继续相邻阶段或识别无结果状态。
    """
    assets = _asset_dir()
    missing = [
        name for name in ("index.html", "app.js", "styles.css") if not (assets / name).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"Monitor frontend assets are missing from {assets}: {', '.join(missing)}"
        )
    server = ThreadingHTTPServer(
        (host, port),
        _handler_factory(
            data_dir.resolve(), assets, quiet=quiet
        ),
    )
    return server


def _refresh_loop(
    stop_event: threading.Event,
    config: AppConfig,
    data_dir: Path,
    refresh_minutes: int,
) -> None:
    """处理：按固定间隔刷新监控快照，并保留上一份可用结果。
    输入：
    - ``stop_event``：后台刷新线程的停止事件；置位后结束下一轮等待和刷新。
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``refresh_minutes``：监控后台线程两次刷新之间的分钟数。
    输出：不返回新数据；完成“按固定间隔刷新监控快照，并保留上一份可用结果”，
      副作用限于该处理声明的受控对象或产物。
    """
    first = True
    while not stop_event.is_set():
        try:
            if (
                first
                and not (data_dir / "monitor" / "snapshot.json").exists()
                or not first
                and refresh_minutes
            ):
                refresh_monitor(config, data_dir)
        except Exception:
            # 刷新失败时保留上一份可读快照；来源级错误继续写入 health.json，
            # 下一次成功刷新再清除连续失败状态。
            pass
        first = False
        if not refresh_minutes or stop_event.wait(refresh_minutes * 60):
            break


def serve_monitor(
    config: AppConfig,
    data_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
    allow_remote: bool = False,
    refresh_minutes: int = 0,
) -> None:
    """处理：启动本地监控服务、可选刷新线程并保持进程运行。
    输入：
    - ``config``：已校验的应用配置；提供时区、来源策略、并发限制、预算和输出选项。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``host``：本地监控服务器绑定的主机地址；远程地址需要显式授权。
    - ``port``：本地监控服务器监听端口；0 表示让操作系统分配可用端口。
    - ``open_browser``：服务器启动后是否在默认浏览器打开监控页面。
    - ``allow_remote``：是否允许监控服务器绑定非环回地址；默认只允许本机访问。
    - ``refresh_minutes``：监控后台线程两次刷新之间的分钟数。
    输出：不返回新数据；完成“启动本地监控服务、可选刷新线程并保持进程运行”，
      副作用限于该处理声明的受控对象或产物。
    """
    if host not in {"127.0.0.1", "localhost", "::1"} and not allow_remote:
        raise ValueError(
            "Refusing to expose the local intelligence desk beyond this machine. "
            "Pass --allow-remote only on a trusted network."
        )
    if refresh_minutes < 0:
        raise ValueError("--refresh-minutes must be zero or a positive integer")
    server = create_monitor_server(data_dir, host, port)
    actual_host, actual_port = server.server_address[:2]
    display_host = "127.0.0.1" if actual_host in {"0.0.0.0", "::"} else actual_host
    url = f"http://{display_host}:{actual_port}/"
    print(f"SignalTrail 新闻情报平台已启动：{url}")
    stop_event = threading.Event()
    refresh_thread = None
    if refresh_minutes > 0:
        refresh_thread = threading.Thread(
            target=_refresh_loop,
            args=(stop_event, config, data_dir, refresh_minutes),
            name="daily-intelligence-monitor-refresh",
            daemon=True,
        )
        refresh_thread.start()
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()
        if refresh_thread:
            refresh_thread.join(timeout=2)
