"""采集材料与未引用原图保留七天，长期报告及其媒体继续保存。"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

COLLECTION_TREES = ("indexes", "content", "snapshots")
TERMINAL = {"completed", "completed_partial", "failed"}
RECYCLE_BATCH_SIZE = 128 if sys.platform == "win32" else 1


def _local_references(value: object, root: Path, field: str = ""):
    """处理：递归提取清单中的本地文件引用。
    输入：运行清单或嵌套数据，以及当前数据根。
    输出：数据根内已有文件的绝对路径。
    """
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _local_references(child, root, key)
    elif isinstance(value, list):
        for child in value:
            yield from _local_references(child, root, field)
    elif isinstance(value, str) and len(value) < 4096:
        path = Path(value)
        if not path.is_absolute():
            if field != "path" and not field.endswith(("_path", "_paths")):
                return
            path = root / path
        path = path.resolve()
        if path.is_relative_to(root) and path.is_file():
            yield path


def _active_references(root: Path) -> set[Path]:
    """处理：沿未结束运行的 JSON 引用追踪依赖。
    输入：包含运行清单、索引和写作会话的数据根。
    输出：仍供活跃运行使用的文件集合，回收阶段跳过这些文件。
    """
    pending = []
    for path in (root / "runs").glob("*/*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") not in TERMINAL or _delivery_pending(record, root):
            pending.extend(_local_references(record, root))
    protected = set()
    while pending:
        path = pending.pop()
        if path in protected:
            continue
        protected.add(path)
        if path.suffix == ".json":
            pending.extend(_local_references(json.loads(path.read_text(encoding="utf-8")), root))
    return protected


def _published_media_references(root: Path) -> set[Path]:
    """处理：保留日报与讲稿 JSON 引用的原图，支持相对媒体路径。
    输入：长期报告、图文及讲稿记录所在的数据根。
    输出：被这些记录引用的图片文件集合，独立 HTML 是否内嵌不影响保护。
    """
    images = root / "media" / "images"
    protected = set()
    for name in ("reports", "narratives"):
        for path in (root / name).rglob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            protected.update(reference for reference in _local_references(record, root)
                             if reference.is_relative_to(images))
    return protected


def _delivery_pending(record: dict, root: Path) -> bool:
    """处理：识别报告已保存但投影或讲稿仍未完成的运行。
    输入：运行清单和数据根；图文完成状态由同计划的已渲染 deck 判断。
    输出：仍需采集材料时为真，已完成日报可按七天策略回收原料。
    """
    if record.get("status") not in {"completed", "completed_partial"}:
        return False
    if record.get("tail", {}).get("status") not in {None, "completed"}:
        return True
    artifacts = record.get("artifacts", {})
    slides = artifacts.get("slides", {})
    if not slides or slides.get("status") == "rendered":
        return False
    if not slides.get("plan_path"):
        return True
    plan = Path(slides["plan_path"])
    for deck in plan.parent.glob("slides-deck-r*.json"):
        saved = json.loads(deck.read_text(encoding="utf-8"))
        ref = saved.get("parents", {}).get("plan", {}).get("path")
        if ref and (root / ref).resolve() == plan.resolve() and deck.with_suffix(".html").is_file():
            report = artifacts.get("json_path")
            sidecar = Path(report).with_name(Path(report).stem + "-slides.html") if report else None
            return bool(sidecar and not sidecar.is_file())
    return True


def _recycle(paths: list[Path]) -> None:
    """处理：一次提交一批过期文件或目录给系统回收站。
    输入：已限定在采集目录内的过期路径。
    输出：系统移走可回收的项目，操作错误交给调用方记录。
    """
    if sys.platform == "win32":
        from send2trash.win.modern import send2trash
    else:
        from send2trash import send2trash
    send2trash([str(path) for path in paths])


def cleanup_collection(data_dir: Path, *, days: int = 7, apply: bool = False,
                       now: datetime | None = None) -> dict:
    """处理：按文件修改时间合并并回收过期采集材料。
    输入：数据根、保留天数、是否执行和可选测量时间。
    输出：候选体积、保护引用数量和失败原因；长期报告、讲稿及其原图继续保留。
    """
    if days < 1:
        raise ValueError("Retention days must be positive")
    root = data_dir.resolve()
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=days)).timestamp()
    protected = _active_references(root) | _published_media_references(root)
    candidates, sizes = [], {}
    retained = 0
    for name in (*COLLECTION_TREES, "media/images"):
        tree = root / name
        if not tree.is_dir() or tree.is_symlink():
            continue
        expired = set()
        paths = list(tree.rglob("*"))
        for path in paths:
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            if resolved in protected:
                retained += 1
            else:
                stat = path.stat()
                if stat.st_mtime < cutoff:
                    expired.add(path)
                    sizes[path] = stat.st_size
        # 先合并完全过期的子目录，减少系统回收站调用数量。
        for directory in sorted((p for p in paths if p.is_dir()),
                                key=lambda p: len(p.parts), reverse=True):
            children = set(directory.iterdir())
            if children and children.issubset(expired) and not directory.is_symlink():
                sizes[directory] = sum(sizes[p] for p in children)
                expired.difference_update(children)
                expired.add(directory)
        candidates.extend(expired)
    snapshot = root / "monitor" / "snapshot.json"
    if (snapshot.is_file() and not snapshot.is_symlink() and snapshot not in protected
            and snapshot.stat().st_mtime < cutoff):
        candidates.append(snapshot)
        sizes[snapshot] = snapshot.stat().st_size
    candidates.sort()
    failures, recycled = [], 0
    recycled_media = []
    if apply:
        for start in range(0, len(candidates), RECYCLE_BATCH_SIZE):
            batch = candidates[start:start + RECYCLE_BATCH_SIZE]
            reason = "Recycle bin left the item at its original path"
            try:
                _recycle(batch)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
            # 系统可能只移走批次的一部分，媒体缓存仅移除已回收路径。
            for path in batch:
                if path.exists():
                    failures.append({"path": str(path), "reason": reason})
                else:
                    recycled += 1
                    if path.is_relative_to(root / "media" / "images"):
                        recycled_media.append(path)
    removed_entries = 0
    cache_path = root / "media" / "image-cache.json"
    if recycled_media and cache_path.is_file():
        from .media import _write_image_cache

        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        recycled_paths = set(recycled_media)
        for url, entry in list(cache["entries"].items()):
            local = entry.get("local_path")
            path = (root / local).resolve() if local else None
            # 回收目录与文件统一按祖先链查集合，避免缓存数乘回收路径数的逐项比较。
            if path and (path in recycled_paths or recycled_paths.intersection(path.parents)):
                del cache["entries"][url]
                removed_entries += 1
        if removed_entries:
            _write_image_cache(root, cache)
    return {"retention_days": days, "dry_run": not apply,
            "candidate_count": len(candidates),
            "candidate_bytes": sum(sizes[p] for p in candidates),
            "protected_count": retained, "recycled_count": recycled,
            "image_cache_entries_removed": removed_entries,
            "candidate_paths": [str(path) for path in candidates], "failures": failures}
