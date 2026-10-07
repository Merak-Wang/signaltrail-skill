from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import now_iso, read_json, write_json

DATA_ROOT_REGISTRY_SCHEMA = "1.0"


def _is_relative_to(path: Path, root: Path) -> bool:
    """处理：判断规范路径是否位于指定根目录之内。
    输入：
    - ``path``：当前函数要读取、校验或写入的本地文件路径。
    - ``root``：安全边界或检查根目录；目标路径必须位于其中。
    输出：布尔判断；True 表示满足处理说明中的条件，False 表示不满足且不产生该结果。
    """
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _migration_binding(data_dir: Path) -> tuple[Path, Path] | None:
    """处理：读取显式迁移登记，或识别同级旧目录已移走的改名。
    输入：当前数据根及应用目录、当前根父目录中的登记表。
    输出：当前根与旧根路径对；两根并存且无登记时返回 None。
    """
    from .config import resolve_signaltrail_home

    root = data_dir.expanduser().resolve()
    for home in dict.fromkeys((resolve_signaltrail_home(), root.parent)):
        payload = _load_data_root_registry(home)
        if payload and payload.get("previous_data_root"):
            current = Path(str(payload["data_root"])).expanduser().resolve()
            previous = Path(str(payload["previous_data_root"])).expanduser().resolve()
            if current == root:
                return current, previous
    legacy = root.parent / "daily-intelligence"
    if root.name == "signaltrail" and not legacy.exists():
        return root, legacy
    return None


def _map_legacy_path(path: Path, data_dir: Path, previous_root: Path | None = None) -> Path:
    """处理：仅在旧目录已移走时，把历史绝对路径映射到同级新目录。
    输入：待读写路径与当前数据根；新旧根同时存在时不猜测迁移方向。
    输出：兼容后的规范路径；磁盘上的历史记录保持原字节不变。
    """
    root = data_dir.expanduser().resolve()
    resolved = path.expanduser().resolve()
    migration = _migration_binding(root) if previous_root is None else None
    legacy = previous_root or (migration[1] if migration else None)
    if legacy and root.exists() and _is_relative_to(resolved, legacy):
        return (root / resolved.relative_to(legacy)).resolve()
    return resolved


def _map_legacy_values(value: Any, data_dir: Path) -> Any:
    """处理：递归转换运行清单内指向旧数据根的绝对路径字符串。
    输入：已读取的 manifest 对象和新数据根；只处理内存副本。
    输出：下游可直接读取的对象，不回写原始 JSON、Markdown 或其哈希。
    """
    root = data_dir.expanduser().resolve()
    migration = _migration_binding(root)
    previous_root = migration[1] if migration else None
    return _map_legacy_value(value, root, previous_root)


def _map_legacy_value(value: Any, root: Path, previous_root: Path | None) -> Any:
    """处理：复用已解析的迁移根递归转换清单路径。
    输入：清单值、当前根和一次读取登记得到的旧根。
    输出：仅内存中更新的嵌套值，供恢复流程读取。
    """
    if isinstance(value, dict):
        return {key: _map_legacy_value(item, root, previous_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_map_legacy_value(item, root, previous_root) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute():
            resolved = path.expanduser().resolve()
            mapped = (root / resolved.relative_to(previous_root)).resolve() if (
                previous_root and root.exists() and _is_relative_to(resolved, previous_root)
            ) else resolved
            if mapped != path.expanduser().resolve():
                return str(mapped)
    return value


def require_data_root_path(path: Path, data_dir: Path, label: str) -> Path:
    """处理：拒绝不属于当前数据根的控制或数据 artifact。
    输入：
    - ``path``：当前函数要读取、校验或写入的本地文件路径。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``label``：用于错误消息的字段或产物名称，使失败能定位到具体输入。
    输出：指向“拒绝不属于当前数据根的控制或数据 artifact”所生成、定位或确认产物的本地路径。
    """
    root = data_dir.expanduser().resolve()
    resolved = _map_legacy_path(path, root)
    if not _is_relative_to(resolved, root):
        raise ValueError(
            f"{label} is outside the active data root: {resolved}. "
            f"Active root: {root}. Re-run with --data-dir {resolved_data_root_hint(resolved)} "
            "or adopt one canonical root before continuing."
        )
    return resolved


def resolved_data_root_hint(path: Path) -> str:
    """处理：从已知 artifact 目录推断数据根，以生成可操作错误。
    输入：
    - ``path``：当前函数要读取、校验或写入的本地文件路径。
    输出：“从已知 artifact 目录推断数据根，以生成可操作错误”得到的规范字符串，
      供调用方存储、比较或展示。
    """
    artifact_directories = {
        "runs",
        "indexes",
        "context",
        "content",
        "content-checkpoints",
        "reports",
        "evaluations",
        "state",
        "publishing",
        "locks",
        "challenges",
    }
    for parent in (path, *path.parents):
        if parent.name in artifact_directories:
            return f'"{parent.parent}"'
    return f'"{path.parent}"'


def validate_run_data_root(run: dict[str, Any], run_path: Path, data_dir: Path) -> Path:
    """处理：校验运行数据根目录并在不满足约束时报告错误。
    输入：
    - ``run``：当前运行清单对象；包含状态、尝试次数、截止时间和产物路径。
    - ``run_path``：运行清单 JSON 路径；记录当前阶段、产物血缘、截止时间和恢复动作。
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    输出：指向“校验运行数据根目录并在不满足约束时报告错误”所生成、定位或确认产物的本地路径。
    """
    root = data_dir.expanduser().resolve()
    # 所有清单与其引用的产物必须属于同一数据根，防止跨运行串写状态。
    require_data_root_path(run_path, root, "Run manifest")
    # 旧运行清单的绝对路径只在内存中换根，磁盘事实文件不被改写。
    run.update(_map_legacy_values(run, root))
    recorded = run.get("data_root")
    if recorded and Path(str(recorded)).expanduser().resolve() != root:
        raise ValueError(
            "Run manifest data_root does not match the active data root: "
            f"run={Path(str(recorded)).expanduser().resolve()}, active={root}"
        )
    artifacts = run.get("artifacts", {})
    if isinstance(artifacts, dict):
        for key in (
            "index_path",
            "context_path",
            "coordinator_path",
            "json_path",
            "markdown_path",
            "html_path",
            "pdf_path",
            "local_index_path",
        ):
            value = artifacts.get(key)
            if value:
                require_data_root_path(Path(str(value)), root, f"Run artifact {key}")
    return root


def data_root_registry_path(app_home: Path) -> Path:
    """处理：定位应用目录下的规范数据根登记表。
    输入：SignalTrail 应用数据目录。
    输出：state 子目录中的登记表路径，供读取与更新使用。
    """
    return app_home.expanduser().resolve() / "state" / "signaltrail-data-root.json"


def _legacy_data_root_registry_path(app_home: Path) -> Path:
    """处理：定位旧名称的数据根登记表以供只读升级兼容。
    输入：SignalTrail 应用数据目录。
    输出：旧版 state 登记表路径；本函数不创建或修改文件。
    """
    return app_home.expanduser().resolve() / "state" / "daily-intelligence-data-root.json"


def _load_data_root_registry(app_home: Path) -> dict[str, Any] | None:
    """处理：读取规范登记或旧名称登记中的数据根记录。
    输入：SignalTrail 应用数据目录。
    输出：有效的登记字典；两处文件都不存在时返回 None。
    """
    registry_path = data_root_registry_path(app_home)
    if not registry_path.exists():
        registry_path = _legacy_data_root_registry_path(app_home)
    if not registry_path.exists():
        return None
    payload = read_json(registry_path)
    if not isinstance(payload, dict) or not payload.get("data_root"):
        raise ValueError(f"Invalid daily-intelligence data-root registry: {registry_path}")
    return payload


def load_bound_data_root(app_home: Path) -> Path | None:
    """处理：直接规范化应用登记的数据根，不推测旧名改迁。
    输入：SignalTrail 应用数据目录及其登记文件。
    输出：规范化的已绑定数据根；无登记时返回 None。
    """
    payload = _load_data_root_registry(app_home)
    if payload is None:
        return None
    return Path(str(payload["data_root"])).expanduser().resolve()


def bind_data_root(
    data_dir: Path,
    app_home: Path,
    *,
    adopt: bool = False,
    timezone: str = "Asia/Shanghai",
) -> dict[str, Any]:
    """处理：将 SignalTrail 应用目录绑定到数据根并显式记录迁移来源。
    输入：
    - ``data_dir``：当前运行的唯一数据根；所有状态和版本化产物都必须位于其中。
    - ``app_home``：SignalTrail 应用目录；其登记表保存唯一数据根绑定。
    - ``adopt``：是否显式接管已有数据根绑定；未授权时冲突会中止。
    - ``timezone``：IANA 时区名称；用于解析无时区时间并生成日报时间边界。
    输出：包含数据根、登记路径和绑定状态的字典；更换既有绑定需显式 adopt。
    """
    root = data_dir.expanduser().resolve()
    home = app_home.expanduser().resolve()

    registry_path = data_root_registry_path(home)
    canonical_registry_exists = registry_path.exists()
    existing = _load_data_root_registry(home)
    previous = Path(str(existing["data_root"])).expanduser().resolve() if existing else None
    if previous and previous != root and not adopt:
        # 更换记录系统必须显式 adopt，避免无意中把一段历史分裂到两个数据根。
        raise ValueError(
            "SignalTrail is already bound to another data root: "
            f"{previous}. Refusing to use {root}. Use `signaltrail --data-dir \"{root}\" "
            "data-root adopt` only after confirming the intended history."
        )
    if previous == root and canonical_registry_exists:
        return {"status": "bound", "registry_path": str(registry_path), **existing}
    payload = {
        "schema_version": DATA_ROOT_REGISTRY_SCHEMA,
        "data_root": str(root),
        "updated_at": now_iso(timezone),
        **({"previous_data_root": str(previous)} if previous and previous != root else {}),
    }
    write_json(registry_path, payload)
    return {
        "status": "adopted" if adopt and previous != root else "bound",
        "registry_path": str(registry_path),
        **payload,
    }
