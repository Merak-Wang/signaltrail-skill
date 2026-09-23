"""Immutable child artifacts; no writes to report, index, or continuity state."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from .runtime import require_data_root_path
from .storage import exclusive_lock, next_revision


def digest(value: object) -> str:
    """处理：对规范 JSON 求摘要以绑定语义。
    输入：上游已经解析的 JSON 数据；不解释其中的文本指令。
    输出：稳定摘要，供草稿、审核和复用决策比较。
    """
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def file_ref(path: Path, data_dir: Path) -> dict:
    """处理：读取数据根内文件并绑定原始字节。
    输入：调用者选定的父文件和唯一数据根。
    输出：相对路径与摘要，供递归加载时验证父版本。
    """
    path = require_data_root_path(path, data_dir, "Explainer parent")
    return {
        "path": path.relative_to(data_dir.resolve()).as_posix(),
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def read_ref(ref: dict, data_dir: Path) -> Path:
    """处理：检查父文件路径和字节摘要。
    输入：由存储器生成的引用及数据根；外部绝对路径不得逃逸。
    输出：已核对的父文件位置；变化或缺失立即中止子产物使用。
    """
    path = require_data_root_path(data_dir / ref["path"], data_dir, "Explainer parent")
    if sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
        raise ValueError(f"Explainer parent changed: {ref['path']}")
    return path


def load_artifact(
    path: Path, data_dir: Path, *, kind: str | None = None, seen: frozenset[str] = frozenset()
) -> dict:
    """处理：加载子产物并递归核对所有父引用。
    输入：明确指定的修订路径，不搜索所谓最新文件；seen 防止引用环。
    输出：通过自身摘要和父闭包校验的记录，供语义门禁及渲染消费。
    """
    path = require_data_root_path(path, data_dir, "Explainer artifact")
    marker = str(path)
    if marker in seen or len(seen) > 24:
        raise ValueError("Explainer parent cycle or excessive depth")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema_version") != "explainer-1.0" or (kind and doc.get("kind") != kind):
        raise ValueError("Unexpected explainer artifact kind/schema")
    if digest({k: v for k, v in doc.items() if k != "content_hash"}) != doc["content_hash"]:
        raise ValueError("Explainer artifact content hash mismatch")
    pair = (
        path.parent
        if path.name == "artifact.json"
        else path.parent / f"{doc['kind']}-r{doc['revision']}"
    ) / "artifact.md"
    if (
        doc.get("markdown_sha256")
        and sha256(pair.read_bytes()).hexdigest() != (doc["markdown_sha256"])
    ):
        raise ValueError("Explainer authoritative Markdown changed")
    for ref in doc["parents"].values():
        parent = read_ref(ref, data_dir)
        if ref["path"].startswith("narratives/") and ref["path"].endswith(".json"):
            load_artifact(parent, data_dir, seen=seen | {marker})
    if kind == "packet" or doc["kind"] == "packet":
        from .narrative_contracts import POLICY

        if doc["payload"]["policy"] != POLICY:
            raise ValueError("Explainer policy changed; prepare a new packet")
    return doc


def save_artifact(
    data_dir: Path,
    session: str,
    kind: str,
    payload: dict,
    parents: dict[str, Path],
    markdown: str = "",
) -> Path:
    """处理：在锁内创建一对不可变 JSON/Markdown 修订并支持精确重放。
    输入：程序分配的会话、类型、已验证内容及明确父版本；Markdown 已确定语义。
    输出：提交成功的 JSON 路径；中断只留下不可见临时目录，不暴露半对文件。
    """
    if not all(c.isalnum() or c in "-_" for c in session + kind):
        raise ValueError("Invalid explainer artifact name")
    directory = data_dir / "narratives" / session
    directory.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(directory / ".write.lock", {"kind": kind}):
        references = {name: file_ref(path, data_dir) for name, path in parents.items()}
        # 所有写入前重读父闭包，隔离旧工作流的可变 packet 和锁前快照问题。
        for ref in references.values():
            if ref["path"].startswith("narratives/") and ref["path"].endswith(".json"):
                load_artifact(read_ref(ref, data_dir), data_dir)
        content = {"payload": payload, "parents": references, "markdown": markdown}
        replay_hash = digest(content)
        for existing in sorted(directory.glob(f"{kind}-r*.json")):
            old = load_artifact(existing, data_dir)
            if old["replay_hash"] == replay_hash:
                return existing
        revision = next_revision(directory, kind)
        # 目录已原子提交但索引未完成时，重放修复索引而不再分配新修订。
        for committed in sorted(directory.glob(f"{kind}-r*/artifact.json")):
            old = load_artifact(committed, data_dir)
            indexed = directory / f"{kind}-r{old['revision']}.json"
            if old["replay_hash"] == replay_hash and not indexed.exists():
                os.link(committed, indexed)
                return indexed
        stem = f"{kind}-r{revision}"
        doc = {
            "schema_version": "explainer-1.0",
            "kind": kind,
            "session": session,
            "revision": revision,
            "created_at": datetime.now(UTC).isoformat(),
            "parents": references,
            "payload": payload,
            "replay_hash": replay_hash,
            "markdown_sha256": sha256(markdown.encode("utf-8")).hexdigest(),
        }
        doc["content_hash"] = digest(doc)
        # 原子重命名目录提交 JSON 与 Markdown；顶层硬链接仅作兼容修订索引。
        staging = directory / f".{stem}-{uuid4().hex}.tmp"
        target = directory / stem
        staging.mkdir()
        try:
            (staging / "artifact.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
            )
            (staging / "artifact.md").write_bytes(markdown.encode("utf-8"))
            # 已提交目录但索引中断时，下一次提交使用新的空闲修订。
            while target.exists():
                revision += 1
                stem = f"{kind}-r{revision}"
                target = directory / stem
            if revision != doc["revision"]:
                doc["revision"] = revision
                doc["content_hash"] = digest({k: v for k, v in doc.items() if k != "content_hash"})
                (staging / "artifact.json").write_text(
                    json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            for ref in references.values():
                read_ref(ref, data_dir)
            _commit_directory(staging, target)
            os.link(target / "artifact.json", directory / f"{stem}.json")
        finally:
            if staging.exists():
                for child in staging.iterdir():
                    child.unlink()
                staging.rmdir()
        return directory / f"{stem}.json"


def _commit_directory(staging: Path, target: Path) -> None:
    """处理：在 Windows 短暂文件占用时有限重试不可变目录提交。
    输入：本次写入创建的临时目录和锁内分配的目标修订目录。
    输出：完整目录原子可见；目标已存在或持续拒绝访问时明确失败，不替换已有修订。
    """
    for attempt in range(5):
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite immutable artifact: {target}")
        try:
            staging.rename(target)
            return
        except PermissionError as exc:
            # Windows 扫描器可短暂持有刚写入文件；只重试拒绝访问/共享锁错误。
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def parent_path(doc: dict, name: str, data_dir: Path) -> Path:
    """处理：从已加载记录取得一个明确的父修订。
    输入：子记录及命名依赖，不使用最新文件扫描。
    输出：通过字节检查的父路径，供下一阶段读取。
    """
    return read_ref(doc["parents"][name], data_dir)
