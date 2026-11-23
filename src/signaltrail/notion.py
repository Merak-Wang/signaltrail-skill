from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import yaml

from .config import project_root
from .local_output import render_report_html
from .localization import localized
from .reporting import validate_evaluation_data, validate_report
from .storage import write_text_atomic
from .utils import canonicalize_url, environment_value, read_json, write_json

_PROPERTY_TYPES: dict[str, set[str]] = {
    "title": {"title"},
    "date": {"date"},
    "version": {"select"},
    "status": {"status", "select"},
    "source": {"select"},
    "tags": {"multi_select"},
    "source_count": {"number"},
    "event_count": {"number"},
    "pending_verification_count": {"number"},
}
_FEEDBACK_PREFIXES = ("用户反馈|", "Reader Feedback|")
_HTML_ATTACHMENT_MODE = "html_attachment_v1"


def validate_notion_schema(config: dict[str, Any], schema: dict[str, Any]) -> None:
    """处理：校验NotionSchema并在不满足约束时报告错误。
    输入：已校验的采集和输出配置。
    - ``schema``：远端或本地 schema 描述；用于字段类型和映射校验。
    输出：不返回新数据；完成“校验NotionSchema并在不满足约束时报告错误”，
      副作用限于该处理声明的受控对象或产物。
    """
    configured = config.get("properties", {})
    actual_properties = schema.get("properties", {})
    errors: list[str] = []

    for required in ("title", "date"):
        if not configured.get(required):
            errors.append(f"missing required mapping properties.{required}")

    for key, name in configured.items():
        allowed_types = _PROPERTY_TYPES.get(key)
        if allowed_types is None:
            errors.append(f"unsupported property mapping: {key}")
            continue
        actual = actual_properties.get(name)
        if actual is None:
            errors.append(f"{key} maps to missing property {name!r}")
            continue
        actual_type = actual.get("type")
        if actual_type not in allowed_types:
            expected = " or ".join(sorted(allowed_types))
            errors.append(f"{name!r} has type {actual_type!r}; expected {expected}")

    status_name = configured.get("status")
    if status_name and status_name in actual_properties:
        status_property = actual_properties[status_name]
        status_type = status_property.get("type")
        option_container = status_property.get(status_type, {}) if status_type else {}
        option_names = {option.get("name") for option in option_container.get("options", [])}
        if option_names:
            values = config.get("values", {})
            for value_key in ("daily_status", "morning_status", "evening_status"):
                status_value = values.get(value_key)
                if status_value and status_value not in option_names:
                    errors.append(
                        f"{value_key}={status_value!r} is not an option of {status_name!r}"
                    )

    if errors:
        raise ValueError(
            "Notion data source schema mismatch: "
            + "; ".join(errors)
            + ". Update configs/notion.yaml or the Notion data source schema."
        )


def resolve_notion_mapping(config: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """处理：在显式属性映射或多个 schema profile 中选择匹配配置。
    输入：已校验的采集和输出配置。
    - ``schema``：远端或本地 schema 描述；用于字段类型和映射校验。
    输出：“在显式属性映射或多个 schema profile 中选择匹配配置”形成的结构化字典；
      键值表达该处理定义的业务记录或查找关系。
    """
    if config.get("properties"):
        validate_notion_schema(config, schema)
        return config

    profiles = config.get("schema_profiles", {})
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("Notion config must define properties or schema_profiles")

    failures: list[str] = []
    # 配置可同时描述多个工作区 schema；按顺序选择首个完整匹配的映射。
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            failures.append(f"{name}: profile must be an object")
            continue
        try:
            validate_notion_schema(profile, schema)
        except ValueError as exc:
            failures.append(f"{name}: {exc}")
            continue
        resolved = dict(profile)
        resolved["profile"] = name
        return resolved

    raise ValueError(
        "Notion data source did not match any configured schema profile: " + " | ".join(failures)
    )


class NotionPublisher:
    """处理：封装 Notion Schema 校验、上传和断点续传发布操作。
    输入：
    - ``token``：调用方从环境或秘密存储读取的 Notion API Token；不会写入本地产物。
    - ``data_source_id``：Notion 报告数据库的数据源 ID；用于查询 schema 和创建页面。
    - ``config_path``：可选配置文件路径；为空时使用仓库或安装包默认配置。
    输出：构造后的 ``NotionPublisher`` 实例或枚举定义；其字段和方法共同承担上述职责。
    """
    def __init__(
        self,
        token: str,
        data_source_id: str,
        config_path: Path | None = None,
    ) -> None:
        """处理：初始化当前实例及其内部状态。
        输入：可选配置文件路径。
        - ``token``：调用方从环境或秘密存储读取的 Notion API Token；不会写入本地产物。
        - ``data_source_id``：Notion 报告数据库的数据源 ID；用于查询 schema 和创建页面。
        输出：不返回新数据；完成“初始化当前实例及其内部状态”，
          副作用限于该处理声明的受控对象或产物。
        """
        config_file = config_path or project_root() / "configs" / "notion.yaml"
        self.config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        self.data_source_id = data_source_id
        self.client = httpx.Client(
            base_url="https://api.notion.com/v1",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": self.config.get("api_version", "2026-03-11"),
                "Accept": "application/json",
            },
            timeout=30,
        )
        self.schema = self._request("GET", f"/data_sources/{data_source_id}")
        try:
            self.mapping = resolve_notion_mapping(self.config, self.schema)
        except Exception:
            self.client.close()
            raise

    def close(self) -> None:
        """处理：关闭客户端并释放底层连接。
        输入：
        - 无显式业务参数：不接收额外业务参数；从当前实例读取“关闭客户端并释放底层连接”所需状态；
          实现会明确读取属性 client。
        输出：不返回新数据；完成“关闭客户端并释放底层连接”，
          副作用限于该处理声明的受控对象或产物。
        """
        self.client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """处理：发送 Notion API 请求，并对限流响应执行有界重试。
        输入：
        - ``method``：要发送的 HTTP 方法。
        - ``path``：当前函数要读取、校验或写入的本地文件路径。
        - ``**kwargs``：传给 Notion HTTP 客户端的受控请求参数，
          例如 headers、json、files 或 data。
        输出：“发送 Notion API 请求，并对限流响应执行有界重试”形成的结构化字典；
          键值表达该处理定义的业务记录或查找关系。
        """
        delay = 1.0
        for attempt in range(5):
            # 文件流在重试前回卷，否则第二次请求会上传空的剩余内容。
            for file_value in kwargs.get("files", {}).values():
                if (
                    isinstance(file_value, tuple)
                    and len(file_value) >= 2
                    and hasattr(file_value[1], "seek")
                ):
                    file_value[1].seek(0)
            response = self.client.request(method, path, **kwargs)
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()
            if attempt == 4:
                response.raise_for_status()
            # 尊重服务端 Retry-After；缺失时采用有上限次数的指数退避。
            retry_after = float(response.headers.get("retry-after", delay))
            time.sleep(retry_after)
            delay *= 2
        raise RuntimeError("Unreachable")

    def retrieve_file_upload(self, file_upload_id: str) -> dict[str, Any]:
        """处理：查询 Notion 文件上传任务的当前状态。
        输入：
        - ``file_upload_id``：Notion 已创建的文件上传 ID；用于查询状态或挂接页面。
        输出：“查询 Notion 文件上传任务的当前状态”形成的结构化字典；
          键值表达该处理定义的业务记录或查找关系。
        """
        return self._request("GET", f"/file_uploads/{file_upload_id}")

    def upload_file(self, path: Path, content_type: str) -> str:
        """处理：创建 Notion 单段上传、发送本地文件并确认上传状态。
        输入：本地文件路径。
        - ``content_type``：HTTP 内容类型或待上传文件 MIME 类型；用于解析、校验和响应头。
        输出：“创建 Notion 单段上传、发送本地文件并确认上传状态”得到的规范字符串，
          供调用方存储、比较或展示。
        """
        if not path.is_file():
            raise FileNotFoundError(f"Notion upload file does not exist: {path}")
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Notion direct file uploads must not exceed 20 MB")
        created = self._request(
            "POST",
            "/file_uploads",
            json={
                "mode": "single_part",
                "filename": path.name,
                "content_type": content_type,
            },
        )
        file_upload_id = str(created["id"])
        with path.open("rb") as handle:
            uploaded = self._request(
                "POST",
                f"/file_uploads/{file_upload_id}/send",
                files={"file": (path.name, handle, content_type)},
            )
        if uploaded.get("status") != "uploaded":
            raise RuntimeError(
                f"Notion file upload {file_upload_id} ended with "
                f"status {uploaded.get('status')!r}"
            )
        return file_upload_id

    def find_page(self, report_date: str) -> str | None:
        """处理：按报告日期查询已有 Notion 日报页面，避免重复创建。
        输入：
        - ``report_date``：写入 Notion 日期属性的日报日期字符串。
        输出：封装“按报告日期查询已有 Notion 日报页面，
          避免重复创建”业务结果的 ``str | None`` 对象；调用方据此继续相邻阶段或识别无结果状态。
        """
        date_property = self.mapping["properties"]["date"]
        if date_property not in self.schema.get("properties", {}):
            return None
        payload = {
            "filter": {
                "property": date_property,
                "date": {"equals": report_date},
            },
            "page_size": 10,
        }
        result = self._request("POST", f"/data_sources/{self.data_source_id}/query", json=payload)
        pages = result.get("results", [])
        return pages[0]["id"] if pages else None

    def build_properties(self, report: dict[str, Any]) -> dict[str, Any]:
        """处理：把报告日期、版本、状态、标签和计数映射为 Notion 属性。
        输入：含栏目和来源引用的报告。
        输出：“把报告日期、版本、状态、标签和计数映射为 Notion 属性”形成的结构化字典；
          典型键包括 date、multi_select、name、number、select、start、status、title。
        """
        configured = self.mapping["properties"]
        schema = self.schema.get("properties", {})
        values = self.mapping.get("values", {})
        edition = report["edition"]
        desired: list[tuple[str, dict[str, Any]]] = []

        def add(key: str, value: dict[str, Any] | None) -> None:
            """处理：向当前集合追加一个规范化条目。
            输入：待解析的值。
            - ``key``：当前集合、登记表或界面记录使用的稳定键。
            输出：不返回新数据；完成“向当前集合追加一个规范化条目”，
              副作用限于该处理声明的受控对象或产物。
            """
            name = configured.get(key)
            if name and value is not None:
                desired.append((name, value))

        add("title", {"title": [_text(report["title"])]})
        add("date", {"date": {"start": report["date"]}})
        version = values.get(f"{edition}_version")
        add("version", {"select": {"name": version}} if version else None)
        status = values.get(f"{edition}_status")
        add("status", {"status": {"name": status}} if status else None)
        source = values.get("source")
        add("source", {"select": {"name": source}} if source else None)
        tags = values.get(f"{edition}_tags", values.get("tags", []))
        add(
            "tags",
            {"multi_select": [{"name": str(tag)} for tag in tags]} if tags else None,
        )
        add("source_count", {"number": report.get("source_count", 0)})
        add("event_count", {"number": report.get("event_count", 0)})
        add(
            "pending_verification_count",
            {"number": len(report.get("pending_verifications", []))},
        )

        properties: dict[str, Any] = {}
        for name, value in desired:
            expected = schema[name]["type"]
            actual = next(iter(value))
            if expected != actual and {expected, actual} <= {"select", "status"}:
                value = {expected: value[actual]}
            properties[name] = value
        return properties

    def create_page(self, report: dict[str, Any]) -> str:
        """处理：按已解析数据库属性创建 Notion 报告页，并分批追加正文块。
        输入：含栏目和来源引用的报告。
        输出：“按已解析数据库属性创建 Notion 报告页，并分批追加正文块”得到的规范字符串，
          供调用方存储、比较或展示。
        """
        payload = {
            "parent": {"type": "data_source_id", "data_source_id": self.data_source_id},
            "properties": self.build_properties(report),
        }
        result = self._request("POST", "/pages", json=payload)
        return result["id"]

    def update_properties(self, page_id: str, report: dict[str, Any]) -> None:
        """处理：把报告属性映射后更新到指定 Notion 页面。
        输入：含栏目和来源引用的报告。
        - ``page_id``：Notion 页面或块 ID；用于读取、更新或追加远端内容。
        输出：不返回新数据；完成“把报告属性映射后更新到指定 Notion 页面”，
          副作用限于该处理声明的受控对象或产物。
        """
        self._request(
            "PATCH",
            f"/pages/{page_id}",
            json={"properties": self.build_properties(report)},
        )

    def append_blocks(
        self,
        page_id: str,
        blocks: list[dict[str, Any]],
        start_block: int = 0,
        on_progress: Callable[[int], None] | None = None,
    ) -> int:
        """处理：分批追加 Notion 块，并在每批后报告持久化进度。
        输入：
        - ``page_id``：Notion 页面或块 ID；用于读取、更新或追加远端内容。
        - ``blocks``：按报告顺序生成的 Notion 块列表；每项包含 type 及对应内容对象。
        - ``start_block``：断点续传时首个尚未追加的 Notion 块下标。
        - ``on_progress``：每完成一个远端步骤调用的检查点回调。
        输出：上述规则计算出的计数、分数、排名或限制值，供确定性决策使用。
        """
        for start in range(start_block, len(blocks), 100):
            completed = min(start + 100, len(blocks))
            self._request(
                "PATCH",
                f"/blocks/{page_id}/children",
                json={"children": blocks[start:completed]},
            )
            if on_progress:
                on_progress(completed)
        return len(blocks)

    def retrieve_blocks(self, page_id: str) -> list[dict[str, Any]]:
        """处理：分页读取指定 Notion 块的全部子块。
        输入：
        - ``page_id``：Notion 页面或块 ID；用于读取、更新或追加远端内容。
        输出：“分页读取指定 Notion 块的全部子块”得到的有序结构化记录；典型字段包括 page_size，
          可直接交给下一阶段。
        """
        blocks: list[dict[str, Any]] = []
        cursor = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            payload = self._request("GET", f"/blocks/{page_id}/children", params=params)
            blocks.extend(payload.get("results", []))
            if not payload.get("has_more"):
                return blocks
            cursor = payload.get("next_cursor")


def _text(content: str) -> dict[str, Any]:
    """处理：将可见文本编码为 Notion 富文本片段。
    输入：报告标题或附件说明。
    输出：截断到 Notion 长度上限的文本对象。
    """
    return {"type": "text", "text": {"content": content[:2000]}}


def _image_block(
    image: dict[str, Any],
    image_uploads: dict[str, str] | None = None,
    language: object = "zh-CN",
) -> dict[str, Any] | None:
    """处理：优先使用已上传文件构造图片块，否则使用安全外链。
    输入：输出语言。
    - ``image``：报告或索引中的图片元数据；包含 URL、本地路径、哈希、尺寸和说明。
    - ``image_uploads``：按本地图片哈希或路径索引的 Notion 文件上传 ID。
    输出：“优先使用已上传文件构造图片块，否则使用安全外链”形成的结构化字典；
      典型键包括 caption、external、file_upload、id、image、object、type、url。
    """
    upload_id = None
    if image_uploads and image.get("sha256"):
        upload_id = image_uploads.get(str(image["sha256"]))
    if upload_id:
        file_data: dict[str, Any] = {
            "type": "file_upload",
            "file_upload": {"id": upload_id},
        }
    else:
        source_url = image.get("source_url") or image.get("url")
        if not isinstance(source_url, str) or not source_url.startswith(
            ("http://", "https://")
        ):
            return None
        file_data = {
            "type": "external",
            "external": {"url": source_url},
        }
    caption = str(image.get("caption") or "")
    credit = str(image.get("credit") or "")
    caption_text = localized(language, "｜来源：", " | Source: ").join(
        part for part in (caption, credit) if part
    )
    return {
        "object": "block",
        "type": "image",
        "image": {
            **file_data,
            "caption": [_text(caption_text)] if caption_text else [],
        },
    }


def parse_user_feedback(text: str) -> dict[str, Any] | None:
    """处理：把 Notion 富文本反馈块解析为本地结构化反馈记录。
    输入：
    - ``text``：待解析、匹配或渲染的文本；作为不可信数据时会先转义或清理。
    输出：“把 Notion 富文本反馈块解析为本地结构化反馈记录”形成的结构化字典；
      典型键包括 accuracy、analysis_value、comment、overall_satisfaction、relevance、scores。
    """
    if not text.startswith(_FEEDBACK_PREFIXES):
        return None
    labels = {
        "relevance": ("相关性", "Relevance"),
        "accuracy": ("准确性", "Accuracy"),
        "analysis_value": ("分析价值", "Analysis Value"),
        "overall_satisfaction": ("整体满意度", "Overall Satisfaction"),
    }
    scores: dict[str, int] = {}
    for key, alternatives in labels.items():
        for label in alternatives:
            match = re.search(rf"{label}\s*=\s*([1-5])", text, re.I)
            if match:
                scores[key] = int(match.group(1))
                break
    comment = ""
    for marker in ("补充意见=", "Additional Comments="):
        if marker in text:
            comment = text.split(marker, 1)[1].strip()
            break
    if not scores and not comment:
        return None
    return {"scores": scores, "comment": comment}


def sync_user_feedback(data_dir: Path, config_path: Path | None = None) -> Path | None:
    """处理：从 Notion 页面读取反馈并同步到本地状态文件。
    输入：本次运行的数据根、可选配置文件路径。
    输出：指向“从 Notion 页面读取反馈并同步到本地状态文件”所生成、定位或确认产物的本地路径；
      条件不满足时返回 None。
    """
    token = environment_value("NOTION_TOKEN")
    data_source_id = environment_value("NOTION_DATA_SOURCE_ID")
    registry_path = data_dir / "publishing" / "notion-registry.json"
    if not token or not data_source_id or not registry_path.exists():
        return None
    registry = read_json(registry_path)
    if not isinstance(registry, dict):
        raise ValueError("Notion publishing registry must be a JSON object")
    entries = sorted(
        (item for item in registry.values() if isinstance(item, dict) and item.get("page_id")),
        key=lambda item: str(item.get("published_at", "")),
        reverse=True,
    )
    if not entries:
        return None
    publisher = NotionPublisher(token, data_source_id, config_path)
    try:
        blocks = publisher.retrieve_blocks(entries[0]["page_id"])
    finally:
        publisher.close()
    feedback_items = []
    for block in blocks:
        kind = block.get("type")
        rich_text = block.get(kind, {}).get("rich_text", []) if kind else []
        text = "".join(item.get("plain_text", "") for item in rich_text)
        parsed = parse_user_feedback(text)
        if parsed:
            feedback_items.append(
                {
                    "feedback_id": block.get("id"),
                    "page_id": entries[0]["page_id"],
                    "captured_at": entries[0].get("published_at"),
                    **parsed,
                }
            )
    if not feedback_items:
        return None
    path = data_dir / "state" / "user-feedback.json"
    write_json(path, {"schema_version": "1.0", "items": feedback_items[-5:]})
    return path


def append_evaluation(
    report_path: Path,
    evaluation_path: Path,
    data_dir: Path,
    config_path: Path | None = None,
) -> tuple[str, str]:
    """处理：把独立质量评估追加到匹配的 Notion 报告页，并返回页面与发布状态。
    输入：版本化报告路径、本次运行的数据根、可选配置文件路径。
    - ``evaluation_path``：独立评估 JSON 路径；读取后追加到对应报告页面。
    输出：“把独立质量评估追加到匹配的 Notion 报告页，并返回页面与发布状态”得到的固定结构结果；
      返回位置依次对应 str(entry['page_id'])、'html_attached'。
    """
    report = read_json(report_path)
    evaluation = read_json(evaluation_path)
    errors = validate_evaluation_data(evaluation, report)
    if errors:
        raise ValueError("Evaluation validation failed: " + "; ".join(errors))
    token = environment_value("NOTION_TOKEN")
    data_source_id = environment_value("NOTION_DATA_SOURCE_ID")
    if not token or not data_source_id:
        raise RuntimeError("NOTION_TOKEN and NOTION_DATA_SOURCE_ID are required")
    registry_path = data_dir / "publishing" / "notion-registry.json"
    registry = read_json(registry_path) if registry_path.exists() else {}
    key = f"{report['date']}:{report['edition']}"
    entry = registry.get(key) if isinstance(registry, dict) else None
    if not isinstance(entry, dict) or not entry.get("page_id"):
        raise RuntimeError("Publish the report before appending its independent evaluation")
    evaluation_id = evaluation["evaluation_id"]
    if evaluation_id in entry.get("evaluation_ids", []):
        return str(entry["page_id"]), "skipped_duplicate"
    publisher = NotionPublisher(token, data_source_id, config_path)
    try:
        portable_html = _portable_report_html(
            report,
            data_dir,
            evaluation=evaluation,
        )
        uploads = entry.setdefault("evaluation_html_uploads", {})
        if not isinstance(uploads, dict):
            uploads = {}
            entry["evaluation_html_uploads"] = uploads
        state = uploads.setdefault(evaluation_id, {})
        if not isinstance(state, dict):
            state = {}
            uploads[evaluation_id] = state

        def save_upload_progress() -> None:
            """处理：把当前附件上传 ID 和状态写入本地发布登记表。
            输入：
            - 无显式业务参数：不接收参数；从外层发布流程捕获当前上传状态、报告条目和持久化回调。
            输出：不返回新数据；完成“把当前附件上传 ID 和状态写入本地发布登记表”，
              副作用限于该处理声明的受控对象或产物。
            """
            write_json(registry_path, registry)

        file_upload_id = _prepare_html_upload(
            publisher,
            portable_html,
            state,
            save_upload_progress,
        )
        publisher.append_blocks(
            str(entry["page_id"]),
            [
                _html_attachment_block(
                    file_upload_id,
                    portable_html,
                    report.get("language") or "zh-CN",
                    evaluated=True,
                )
            ],
        )
    finally:
        publisher.close()
    entry.setdefault("evaluation_ids", []).append(evaluation_id)
    entry["evaluation_status"] = "completed"
    write_json(registry_path, registry)
    return str(entry["page_id"]), "html_attached"


def _local_report_images(
    report: dict[str, Any],
    data_dir: Path,
) -> dict[str, tuple[Path, str]]:
    """处理：校验报告引用的本地图片并按内容哈希建立索引。
    输入：含栏目和来源引用的报告、本次运行的数据根。
    输出：“校验报告引用的本地图片并按内容哈希建立索引”形成的结构化字典；
      键值表达该处理定义的业务记录或查找关系。
    """
    root = data_dir.resolve()
    images: dict[str, tuple[Path, str]] = {}
    for section in report.get("sections", []):
        if not isinstance(section, dict):
            continue
        for collection in ("briefs", "items"):
            for item in section.get(collection, []):
                if not isinstance(item, dict) or not isinstance(item.get("image"), dict):
                    continue
                image = item["image"]
                digest = str(image.get("sha256") or "")
                relative_path = image.get("local_path")
                content_type = str(image.get("content_type") or "")
                if not digest or not isinstance(relative_path, str) or not content_type:
                    continue
                path = (root / relative_path).resolve()
                if not path.is_relative_to(root):
                    raise ValueError(
                        f"Report image path escapes the configured data root: {relative_path}"
                    )
                images.setdefault(digest, (path, content_type))
    return images


def _file_sha256(path: Path) -> str:
    """处理：流式计算文件 SHA-256，避免一次读取整个附件。
    输入：本地文件路径。
    输出：“流式计算文件 SHA-256，避免一次读取整个附件”得到的规范字符串，
      供调用方存储、比较或展示。
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _saved_upload_id(value: object) -> str | None:
    """处理：从发布检查点提取可复用的 Notion 上传 ID。
    输入：待解析的值。
    输出：封装“从发布检查点提取可复用的 Notion 上传 ID”业务结果的 ``str | None`` 对象；
      调用方据此继续相邻阶段或识别无结果状态。
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("id"):
        return str(value["id"])
    return None


def _portable_report_html(
    report: dict[str, Any],
    data_dir: Path,
    *,
    evaluation: dict[str, Any] | None = None,
) -> Path:
    """处理：生成可独立打开的报告 HTML 附件，图片使用公共来源地址。
    输入：已校验日报、本次运行数据根及可选独立评估。
    输出：可供上传并记录哈希的 HTML 文件路径。
    """
    report_id = str(report.get("report_id") or "").strip()
    if not report_id:
        raise ValueError("Report requires report_id before Notion publication")
    suffix = (
        f"-{evaluation['evaluation_id']}"
        if isinstance(evaluation, dict) and evaluation.get("evaluation_id")
        else ""
    )
    output = data_dir / "publishing" / "notion-html" / f"{report_id}{suffix}.html"
    return write_text_atomic(
        output,
        render_report_html(
            report,
            evaluation,
            include_pdf_link=False,
            media_path_prefix=None,
        ),
    )


def _html_attachment_block(
    file_upload_id: str,
    path: Path,
    language: object,
    *,
    evaluated: bool = False,
) -> dict[str, Any]:
    """处理：构造指向已上传 HTML 报告的 Notion 文件块。
    输入：本地文件路径、输出语言。
    - ``file_upload_id``：Notion 已创建的文件上传 ID；用于查询状态或挂接页面。
    - ``evaluated``：报告是否已有独立评估；决定附件块的说明文本。
    输出：“构造指向已上传 HTML 报告的 Notion 文件块”形成的结构化字典；
      典型键包括 caption、file、file_upload、id、name、object、type。
    """
    caption = localized(
        language,
        "含独立评估的完整 HTML 日报" if evaluated else "完整 HTML 日报",
        "Complete HTML report with independent evaluation"
        if evaluated
        else "Complete HTML report",
    )
    return {
        "object": "block",
        "type": "file",
        "file": {
            "type": "file_upload",
            "file_upload": {"id": file_upload_id},
            "name": path.name,
            "caption": [_text(caption)],
        },
    }


def _prepare_html_upload(
    publisher: NotionPublisher,
    path: Path,
    state: dict[str, Any],
    on_progress: Callable[[], None],
) -> str:
    """处理：校验已有上传检查点或创建新的 HTML 文件上传。
    输入：本地文件路径。
    - ``publisher``：已校验 schema 且具备断点续传能力的 Notion 发布客户端。
    - ``state``：可恢复发布状态对象；记录已创建页面、文件上传和完成检查点。
    - ``on_progress``：每完成一个远端步骤调用的检查点回调。
    输出：“校验已有上传检查点或创建新的 HTML 文件上传”得到的规范字符串，
      供调用方存储、比较或展示。
    """
    digest = _file_sha256(path)
    saved_id = _saved_upload_id(state)
    if saved_id and state.get("sha256") == digest:
        try:
            saved = publisher.retrieve_file_upload(saved_id)
        except Exception:
            saved = {}
        if saved.get("status") == "uploaded":
            return saved_id
    file_upload_id = publisher.upload_file(path, "text/html")
    state.clear()
    state.update(
        {
            "id": file_upload_id,
            "sha256": digest,
            "local_path": str(path),
            "content_type": "text/html",
        }
    )
    on_progress()
    return file_upload_id


def _prepare_image_uploads(
    publisher: NotionPublisher,
    report: dict[str, Any],
    data_dir: Path,
    entry: dict[str, Any],
    on_progress: Callable[[], None],
) -> tuple[dict[str, str], dict[str, str]]:
    """处理：逐张校验并上传本地图片，同时持久化断点状态。
    输入：
    - ``publisher``：已校验 schema 且具备断点续传能力的 Notion 发布客户端。
    - ``report``：当前报告结构；包含栏目、简报或事件、来源引用及质量元数据。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``entry``：报告中带本地图片元数据的简报或事件记录；
      读取 item_id、标题、图片路径和内容哈希。
    - ``on_progress``：每完成一个远端步骤调用的检查点回调。
    输出：“逐张校验并上传本地图片，同时持久化断点状态”得到的固定结构结果；
      返回位置依次对应 resolved、errors。
    """
    local_images = _local_report_images(report, data_dir)
    state = entry.setdefault("image_uploads", {})
    if not isinstance(state, dict):
        state = {}
        entry["image_uploads"] = state
    errors: dict[str, str] = {}
    resolved: dict[str, str] = {}
    for digest, (path, content_type) in local_images.items():
        saved_id = _saved_upload_id(state.get(digest))
        if saved_id:
            try:
                saved = publisher.retrieve_file_upload(saved_id)
            except Exception:
                saved = {}
            if saved.get("status") == "uploaded":
                resolved[digest] = saved_id
                continue
        try:
            if not path.is_file():
                raise FileNotFoundError(f"local image file is missing: {path}")
            if _file_sha256(path) != digest:
                raise ValueError(f"local image hash does not match report metadata: {path}")
            file_upload_id = publisher.upload_file(path, content_type)
        except Exception as exc:
            state.pop(digest, None)
            errors[digest] = f"{type(exc).__name__}: {str(exc)[:500]}"
        else:
            state[digest] = {
                "id": file_upload_id,
                "local_path": str(path.relative_to(data_dir.resolve()).as_posix()),
                "content_type": content_type,
            }
            resolved[digest] = file_upload_id
        entry["image_upload_errors"] = errors
        on_progress()
    entry["image_upload_errors"] = errors
    return resolved, errors


def _block_plain_text(block: dict[str, Any]) -> str:
    """处理：从 Notion 块中拼接可比较的纯文本。
    输入：
    - ``block``：Notion API 返回或待发布的单个块对象；读取类型、富文本和链接字段。
    输出：“从 Notion 块中拼接可比较的纯文本”得到的规范字符串，供调用方存储、比较或展示。
    """
    kind = block.get("type")
    if not isinstance(kind, str):
        return ""
    rich_text = block.get(kind, {}).get("rich_text", [])
    return "".join(
        str(item.get("plain_text") or item.get("text", {}).get("content") or "")
        for item in rich_text
        if isinstance(item, dict)
    )


def _block_link_url(block: dict[str, Any]) -> str | None:
    """处理：遍历 Notion 块的 rich_text 片段并返回首个合法 HTTP(S) 链接。
    输入：
    - ``block``：Notion API 返回或待发布的单个块对象；读取类型、富文本和链接字段。
    输出：封装“遍历 Notion 块的 rich_text 片段并返回首个合法 HTTP(S) 链接”业务结果的 ``str | Non
      e`` 对象；调用方据此继续相邻阶段或识别无结果状态。
    """
    kind = block.get("type")
    if not isinstance(kind, str):
        return None
    for item in block.get(kind, {}).get("rich_text", []):
        if not isinstance(item, dict):
            continue
        url = item.get("href") or item.get("text", {}).get("link", {}).get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    return None


def _edition_story_blocks(
    blocks: list[dict[str, Any]],
    edition: str,
    language: object = "zh-CN",
) -> list[dict[str, Any]]:
    """处理：定位指定日报版本分区并提取其中的故事列表块。
    输入：输出语言。
    - ``blocks``：按报告顺序生成的 Notion 块列表；每项包含 type 及对应内容对象。
    - ``edition``：日报版本标识，通常为 morning 或 evening；参与窗口和产物命名。
    输出：“定位指定日报版本分区并提取其中的故事列表块”得到的有序结构化记录；
      每项承载处理说明所定义的身份、证据或状态字段，可直接交给下一阶段。
    """
    label = (
        localized(language, "日报", "Daily Brief")
        if edition == "daily" else
        localized(language, "06:00 早报", "06:00 Morning Brief")
        if edition == "morning"
        else localized(language, "18:00 晚报", "18:00 Evening Brief")
    )
    in_edition = False
    stories: list[dict[str, Any]] = []
    for block in blocks:
        if in_edition and block.get("type") == "divider":
            break
        if (
            block.get("type") == "heading_2"
            and _block_plain_text(block).strip() == label
        ):
            in_edition = True
            continue
        if in_edition and block.get("type") == "numbered_list_item":
            stories.append(block)
    if not in_edition:
        raise RuntimeError(
            f"Could not find the {label!r} section on the registered Notion page"
        )
    return stories


def _report_items_with_images(
    report: dict[str, Any],
) -> list[tuple[str, str, dict[str, Any]]]:
    """处理：列出报告中同时具有来源 URL 和图片的条目。
    输入：含栏目和来源引用的报告。
    输出：按“列出报告中同时具有来源 URL 和图片的条目”规则得到的 ``tuple[str, str, dict[str, Any`
      ` 列表；列表顺序表达配置优先级、业务排名或稳定扫描顺序。
    """
    items: list[tuple[str, str, dict[str, Any]]] = []
    for section in report.get("sections", []):
        if not isinstance(section, dict):
            continue
        for collection in ("briefs", "items"):
            for item in section.get(collection, []):
                if not isinstance(item, dict) or not isinstance(item.get("image"), dict):
                    continue
                ref = item.get("source_ref")
                if not isinstance(ref, dict):
                    refs = item.get("source_refs", [])
                    ref = refs[0] if isinstance(refs, list) and refs else {}
                url = ref.get("url") if isinstance(ref, dict) else None
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    items.append((str(item.get("item_id") or ""), url, item["image"]))
    return items


def backfill_report_images(
    report_path: Path,
    data_dir: Path,
    config_path: Path | None = None,
) -> tuple[str, str]:
    """处理：向已有故事块补充缺失图片，同时避免重复创建日报。
    输入：版本化报告路径、本次运行的数据根、可选配置文件路径。
    输出：“向已有故事块补充缺失图片，同时避免重复创建日报”得到的固定结构结果；
      返回位置依次对应 page_id、status。
    """
    errors, _warnings = validate_report(report_path)
    if errors:
        raise ValueError("Report validation failed: " + "; ".join(errors))
    report = read_json(report_path)
    if not isinstance(report, dict):
        raise ValueError("Report must be a JSON object")
    image_items = _report_items_with_images(report)
    if not image_items:
        raise ValueError("Report contains no materialized images to backfill")

    token = environment_value("NOTION_TOKEN")
    data_source_id = environment_value("NOTION_DATA_SOURCE_ID")
    if not token or not data_source_id:
        raise RuntimeError("NOTION_TOKEN and NOTION_DATA_SOURCE_ID are required")

    registry_path = data_dir / "publishing" / "notion-registry.json"
    registry = read_json(registry_path) if registry_path.exists() else {}
    if not isinstance(registry, dict):
        raise ValueError("Notion publishing registry must be a JSON object")
    key = f"{report['date']}:{report['edition']}"
    entry = registry.get(key)
    if not isinstance(entry, dict) or not entry.get("page_id"):
        raise RuntimeError("Publish the report before backfilling its images")

    page_id = str(entry["page_id"])
    if entry.get("publication_mode") == _HTML_ATTACHMENT_MODE:
        return page_id, "not_applicable_html_attachment"
    progress = {
        "status": "publishing",
        "report_id": report["report_id"],
        "revision": report["revision"],
        "target_images": len(image_items),
        "appended": 0,
        "already_present": 0,
        "missing_item_ids": [],
    }
    entry["image_backfill"] = progress
    write_json(registry_path, registry)

    publisher = NotionPublisher(token, data_source_id, config_path)
    try:
        def save_progress() -> None:
            """处理：把当前远程写入进度写入本地发布登记表。
            输入：
            - 无显式业务参数：不接收参数；从外层发布流程捕获当前页面、块进度和可恢复状态。
            输出：不返回新数据；完成“把当前远程写入进度写入本地发布登记表”，
              副作用限于该处理声明的受控对象或产物。
            """
            write_json(registry_path, registry)

        image_uploads, image_upload_errors = _prepare_image_uploads(
            publisher,
            report,
            data_dir,
            entry,
            save_progress,
        )
        stories = _edition_story_blocks(
            publisher.retrieve_blocks(page_id),
            str(report["edition"]),
            report.get("language") or "zh-CN",
        )
        stories_by_url: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for story in stories:
            url = _block_link_url(story)
            if url:
                stories_by_url[canonicalize_url(url)].append(story)

        used_block_ids: set[str] = set()
        for item_id, url, image in image_items:
            matches = stories_by_url.get(canonicalize_url(url))
            while matches and str(matches[0].get("id") or "") in used_block_ids:
                matches.popleft()
            if not matches:
                progress["missing_item_ids"].append(item_id)
                save_progress()
                continue
            story_id = str(matches[0].get("id") or "")
            if not story_id:
                progress["missing_item_ids"].append(item_id)
                save_progress()
                continue
            matches.popleft()
            used_block_ids.add(story_id)
            children = publisher.retrieve_blocks(story_id)
            if any(child.get("type") == "image" for child in children):
                progress["already_present"] += 1
                save_progress()
                continue
            image_block = _image_block(
                image,
                image_uploads,
                report.get("language") or "zh-CN",
            )
            if image_block is None:
                progress["missing_item_ids"].append(item_id)
                save_progress()
                continue
            publisher.append_blocks(story_id, [image_block])
            progress["appended"] += 1
            save_progress()
    finally:
        publisher.close()

    progress["status"] = "partial" if progress["missing_item_ids"] else "complete"
    entry["media_report_id"] = report["report_id"]
    entry["media_revision"] = report["revision"]
    entry["media_status"] = (
        "external_fallback" if image_upload_errors else "uploaded"
    )
    write_json(registry_path, registry)
    if progress["missing_item_ids"]:
        status = "images_backfilled_partial"
    elif progress["appended"] == 0:
        status = "skipped_already_present"
    elif image_upload_errors:
        status = "images_backfilled_with_fallbacks"
    else:
        status = "images_backfilled"
    return page_id, status


def publish_report(
    report_path: Path,
    data_dir: Path,
    force: bool = False,
    config_path: Path | None = None,
) -> tuple[str, str]:
    """处理：校验本地权威报告并以可续传 HTML 附件方式发布到 Notion。
    输入：
    - ``report_path``：已在本地通过 schema 与语义校验的版本化报告 JSON 路径；
      它是远程发布的唯一内容来源。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``force``：是否忽略正常缓存或重复保护并显式重新执行允许的步骤。
    - ``config_path``：可选配置文件路径；为空时使用仓库或安装包默认配置。
    输出：Notion 页面 ID 与发布结果状态；状态可区分新发布、重复跳过或恢复完成。
    """
    errors, _warnings = validate_report(report_path)
    if errors:
        raise ValueError("Report validation failed: " + "; ".join(errors))

    report = read_json(report_path)
    if not isinstance(report, dict):
        raise ValueError("Report must be a JSON object")

    token = environment_value("NOTION_TOKEN")
    data_source_id = environment_value("NOTION_DATA_SOURCE_ID")
    if not token or not data_source_id:
        raise RuntimeError("NOTION_TOKEN and NOTION_DATA_SOURCE_ID are required")

    registry_path = data_dir / "publishing" / "notion-registry.json"
    registry = read_json(registry_path) if registry_path.exists() else {}
    if not isinstance(registry, dict):
        raise ValueError("Notion publishing registry must be a JSON object")

    key = f"{report['date']}:{report['edition']}"
    existing = registry.get(key)
    if isinstance(existing, dict) and not force:
        if existing.get("status", "complete") == "complete":
            # 本地登记表是幂等依据，已完成的同一版本不会再次创建页面或附件。
            return existing["page_id"], "skipped_duplicate"
        if existing.get("report_id") != report["report_id"]:
            raise RuntimeError(
                "An interrupted publish exists for a different report_id; "
                "resolve it before publishing this edition"
            )
        if existing.get("publication_mode") != _HTML_ATTACHMENT_MODE:
            raise RuntimeError(
                "An interrupted legacy rich-text publish cannot resume as an HTML "
                "attachment. Resolve the partial Notion page, then publish again with "
                "--force."
            )

    publisher = NotionPublisher(token, data_source_id, config_path)
    try:
        if isinstance(existing, dict) and not force:
            page_id = existing["page_id"]
            start_block = int(existing.get("blocks_appended", 0))
            publisher.update_properties(page_id, report)
        else:
            page_id = publisher.find_page(report["date"])
            if not page_id:
                page_id = publisher.create_page(report)
            else:
                publisher.update_properties(page_id, report)
            start_block = 0
        if start_block not in {0, 1}:
            raise RuntimeError(
                f"HTML attachment publish checkpoint is invalid: {start_block}"
            )
        prior_html_upload = (
            existing.get("html_upload", {})
            if isinstance(existing, dict)
            and existing.get("report_id") == report["report_id"]
            and existing.get("publication_mode") == _HTML_ATTACHMENT_MODE
            else {}
        )
        if not isinstance(prior_html_upload, dict):
            prior_html_upload = {}
        entry = {
            "page_id": page_id,
            "report_id": report["report_id"],
            "revision": report["revision"],
            "published_at": report["generated_at"],
            "status": "publishing",
            "publication_mode": _HTML_ATTACHMENT_MODE,
            "blocks_appended": start_block,
            "blocks_total": 1,
            "html_upload": prior_html_upload,
        }
        if isinstance(existing, dict) and existing.get("evaluation_ids"):
            entry["evaluation_ids"] = existing["evaluation_ids"]
        registry[key] = entry
        # 先记录远端页面身份和发布模式，再上传附件，进程中断后才能安全续传。
        write_json(registry_path, registry)

        def save_upload_progress() -> None:
            """处理：把当前附件上传 ID 和状态写入本地发布登记表。
            输入：
            - 无显式业务参数：不接收参数；从外层发布流程捕获当前上传状态、报告条目和持久化回调。
            输出：不返回新数据；完成“把当前附件上传 ID 和状态写入本地发布登记表”，
              副作用限于该处理声明的受控对象或产物。
            """
            write_json(registry_path, registry)

        portable_html = _portable_report_html(report, data_dir)
        html_upload_id = _prepare_html_upload(
            publisher,
            portable_html,
            entry["html_upload"],
            save_upload_progress,
        )
        blocks = [
            _html_attachment_block(
                html_upload_id,
                portable_html,
                report.get("language") or "zh-CN",
            )
        ]
        # 附件上传完成后再次落盘 upload_id，随后才开始修改页面块。
        write_json(registry_path, registry)

        def save_progress(completed: int) -> None:
            """处理：把当前远程写入进度写入本地发布登记表。
            输入：
            - ``completed``：已经成功持久化的项目数；用于发布进度检查点。
            输出：不返回新数据；完成“把当前远程写入进度写入本地发布登记表”，
              副作用限于该处理声明的受控对象或产物。
            """
            entry["blocks_appended"] = completed
            write_json(registry_path, registry)

        publisher.append_blocks(
            page_id,
            blocks,
            start_block=start_block,
            on_progress=save_progress,
        )
        # 每个块的追加进度由回调持续检查点化；最终状态只在全部完成后置为 complete。
        entry["status"] = "complete"
        entry["blocks_appended"] = len(blocks)
        write_json(registry_path, registry)
        return page_id, "published"
    finally:
        publisher.close()
