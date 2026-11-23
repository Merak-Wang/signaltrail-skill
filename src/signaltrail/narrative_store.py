"""Immutable child artifacts; no writes to report, index, or continuity state."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from .runtime import require_data_root_path
from .storage import exclusive_lock, next_revision
from .utils import sha256_file


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
        "sha256": sha256_file(path),
    }


def read_ref(ref: dict, data_dir: Path) -> Path:
    """处理：检查父文件路径和字节摘要。
    输入：由存储器生成的引用及数据根；外部绝对路径不得逃逸。
    输出：已核对的父文件位置；变化或缺失立即中止子产物使用。
    """
    path = require_data_root_path(data_dir / ref["path"], data_dir, "Explainer parent")
    if sha256_file(path) != ref["sha256"]:
        raise ValueError(f"Explainer parent changed: {ref['path']}")
    return path


class ArtifactReader:
    """处理：在一次操作内共享不可变产物的字节摘要与已验证父链。
    输入：本次操作的唯一数据根，每条父引用仍与所读字节比较。
    输出：供当前操作只读使用的产物记录；下一次操作重新读取文件。
    """

    def __init__(self, data_dir: Path) -> None:
        """处理：创建本次操作的空读取表。
        输入：产物和父文件所在的已绑定数据根。
        输出：缓存仅随该读取器存活，不跨操作保存。
        """
        self.data_dir = data_dir.resolve()
        self._hashes: dict[Path, str] = {}
        self._artifacts: dict[Path, tuple[dict, int]] = {}

    def _hash(self, path: Path) -> str:
        """处理：首次读取文件并记录字节摘要。
        输入：已经限定在数据根的文件路径。
        输出：字节摘要，供同一操作中的多个父引用比较。
        """
        if path not in self._hashes:
            self._hashes[path] = sha256_file(path)
        return self._hashes[path]

    def parent_path(self, doc: dict, name: str) -> Path:
        """处理：定位并核对指定父文件的摘要。
        输入：已加载子产物及其依赖名称。
        输出：已核对的父文件路径，摘要不同则拒绝引用。
        """
        ref = doc["parents"][name]
        path = require_data_root_path(self.data_dir / ref["path"], self.data_dir,
                                      "Explainer parent")
        if self._hash(path) != ref["sha256"]:
            raise ValueError(f"Explainer parent changed: {ref['path']}")
        return path

    def parent_json(self, doc: dict, name: str) -> dict:
        """处理：按摘要校验后解码索引或报告父文件。
        输入：已加载子产物的父引用。
        输出：直接从已核对字节解码的对象，供渲染消费。
        """
        ref = doc["parents"][name]
        path = require_data_root_path(self.data_dir / ref["path"], self.data_dir,
                                      "Explainer parent")
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError(f"Explainer parent changed: {ref['path']}")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"Explainer parent must contain a JSON object: {ref['path']}")
        return value

    def validated_ref(self, path: Path) -> dict:
        """处理：导出本次操作已验证产物的摘要引用。
        输入：通过本读取器加载并完成闭包校验的路径。
        输出：供提交阶段核对的原始父引用，不重新读取或绑定新版本。
        """
        path = require_data_root_path(path, self.data_dir, "Explainer parent")
        if path not in self._artifacts:
            raise ValueError(f"Artifact was not validated: {path.relative_to(self.data_dir)}")
        return {"path": path.relative_to(self.data_dir).as_posix(), "sha256": self._hashes[path]}

    def load(self, path: Path, *, kind: str | None = None,
             seen: frozenset[Path] = frozenset(), expected_hash: str | None = None) -> dict:
        """处理：验证 JSON、权威 Markdown 和全部父引用。
        输入：修订路径、可选类型、当前递归路径和父引用预期摘要。
        输出：只读记录；共享父链只解码一次，仍限制最长引用深度。
        """
        path = require_data_root_path(path, self.data_dir, "Explainer artifact")
        if path in seen or len(seen) > 24:
            raise ValueError("Explainer parent cycle or excessive depth")
        if path in self._artifacts:
            if expected_hash is not None and self._hashes[path] != expected_hash:
                raise ValueError(f"Explainer parent changed: {path.relative_to(self.data_dir)}")
            doc, depth = self._artifacts[path]
            if len(seen) + depth > 24:
                raise ValueError("Explainer parent cycle or excessive depth")
            if kind and doc.get("kind") != kind:
                raise ValueError("Unexpected explainer artifact kind/schema")
            return doc
        raw = path.read_bytes()
        file_hash = sha256(raw).hexdigest()
        if (file_hash != self._hashes.get(path, file_hash)
                or (expected_hash is not None and file_hash != expected_hash)):
            raise ValueError(f"Explainer parent changed: {path.relative_to(self.data_dir)}")
        self._hashes[path] = file_hash
        doc = json.loads(raw.decode("utf-8"))
        if doc.get("schema_version") != "explainer-1.0" or (kind and doc.get("kind") != kind):
            raise ValueError("Unexpected explainer artifact kind/schema")
        if digest({k: v for k, v in doc.items() if k != "content_hash"}) != doc["content_hash"]:
            raise ValueError("Explainer artifact content hash mismatch")
        pair = (path.parent if path.name == "artifact.json" else
                path.parent / f"{doc['kind']}-r{doc['revision']}") / "artifact.md"
        if doc.get("markdown_sha256") and self._hash(pair) != doc["markdown_sha256"]:
            raise ValueError("Explainer authoritative Markdown changed")
        depth = 0
        for name, ref in doc["parents"].items():
            if ref["path"].startswith("narratives/") and ref["path"].endswith(".json"):
                parent = self.data_dir / ref["path"]
                self.load(parent, seen=seen | {path}, expected_hash=ref["sha256"])
                parent = parent.resolve()
                depth = max(depth, self._artifacts[parent][1] + 1)
            else:
                self.parent_path(doc, name)
        self._artifacts[path] = (doc, depth)
        return doc


def load_artifact(path: Path, data_dir: Path, *, kind: str | None = None) -> dict:
    """处理：独立加载子产物并递归核对所有父引用。
    输入：调用者指定的修订文件、数据根和可选类型。
    输出：通过自身摘要和父闭包校验的记录，下一次调用重新验证。
    """
    return ArtifactReader(data_dir).load(path, kind=kind)


def save_artifact(
    data_dir: Path,
    session: str,
    kind: str,
    payload: dict,
    parents: dict[str, Path],
    markdown: str = "",
    *,
    expected_parents: dict[str, dict] | None = None,
) -> Path:
    """处理：在锁内创建一对不可变 JSON/Markdown 修订并支持精确重放。
    输入：会话、类型、已验证内容及父版本，可附构造内容时验证的父摘要。
    输出：提交成功的 JSON 路径；中断只留下不可见临时目录，不暴露半对文件。
    """
    return _save_artifacts(data_dir, session, [(kind, payload, markdown)], parents,
                           expected_parents=expected_parents)[0]


def save_artifact_siblings(
    data_dir: Path,
    session: str,
    payloads: Iterable[tuple[str, dict]],
    parents: dict[str, Path],
) -> list[Path]:
    """处理：共用父链检查和写锁，按顺序提交同一计划的独立修订。
    输入：按批次生成的类型与内容，以及所有批次引用的同一组父文件。
    输出：有序修订路径，重试复用已经提交的批次。
    """
    return _save_artifacts(data_dir, session, ((kind, payload, "") for kind, payload in payloads),
                           parents)


def _save_artifacts(
    data_dir: Path,
    session: str,
    artifacts: Iterable[tuple[str, dict, str]],
    parents: dict[str, Path],
    *,
    expected_parents: dict[str, dict] | None = None,
) -> list[Path]:
    """处理：在同一写锁内校验共享父链并提交各个不可变修订。
    输入：类型、内容、Markdown 三元组及父文件。
    输出：各修订路径；输入为空时不创建会话或加锁。
    """
    specs = list(artifacts)
    if not specs:
        return []
    if not all(c.isalnum() or c in "-_" for c in session + "".join(k for k, _, _ in specs)):
        raise ValueError("Invalid explainer artifact name")
    directory = data_dir / "narratives" / session
    directory.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(directory / ".write.lock", {"kind": specs[0][0]}):
        reader = ArtifactReader(data_dir)
        references = {name: file_ref(path, data_dir) for name, path in parents.items()}
        if expected_parents is not None and references != expected_parents:
            raise ValueError("Explainer parent changed before artifact commit")
        # 所有写入前重读父闭包，隔离旧工作流的可变 packet 和锁前快照问题。
        for ref in references.values():
            if ref["path"].startswith("narratives/") and ref["path"].endswith(".json"):
                reader.load(data_dir / ref["path"], expected_hash=ref["sha256"])
        return [
            _write_revision(reader, directory, session, kind, payload, markdown, references)
            for kind, payload, markdown in specs
        ]


def _write_revision(
    reader: ArtifactReader,
    directory: Path,
    session: str,
    kind: str,
    payload: dict,
    markdown: str,
    references: dict[str, dict],
) -> Path:
    """处理：在已有会话写锁内查找精确重放或提交新的 JSON/Markdown 对。
    输入：已核对父链的读取器和待提交修订。
    输出：已提交的修订索引。
    """
    content = {"payload": payload, "parents": references, "markdown": markdown}
    replay_hash = digest(content)
    for existing in sorted(directory.glob(f"{kind}-r*.json")):
        old = reader.load(existing)
        if old["replay_hash"] == replay_hash:
            return existing
    revision = next_revision(directory, kind)
    # 目录已原子提交但索引未完成时，重放修复索引而不再分配新修订。
    for committed in sorted(directory.glob(f"{kind}-r*/artifact.json")):
        old = reader.load(committed)
        indexed = directory / f"{kind}-r{old['revision']}.json"
        if old["replay_hash"] == replay_hash and not indexed.exists():
            os.link(committed, indexed)
            return indexed
    # 已提交目录但索引中断时，下一次提交使用新的空闲修订。
    stem = f"{kind}-r{revision}"
    target = directory / stem
    while target.exists():
        revision += 1
        stem = f"{kind}-r{revision}"
        target = directory / stem
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
    staging.mkdir()
    try:
        (staging / "artifact.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        (staging / "artifact.md").write_bytes(markdown.encode("utf-8"))
        for ref in references.values():
            read_ref(ref, reader.data_dir)
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
