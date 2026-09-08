import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_code_comments",
    ROOT / "scripts" / "check_code_comments.py",
)
assert SPEC and SPEC.loader
CODE_COMMENTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CODE_COMMENTS)


def test_maintained_python_definitions_have_semantic_chinese_contracts():
    assert CODE_COMMENTS.validate_code_comments() == []


def test_comment_checks_include_nested_packages_and_accept_concise_inputs(tmp_path):
    source = tmp_path / "src/daily_intelligence/commands/monitor.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'def load(path):\n'
        '    """处理：读取监控快照。\n'
        '    输入：path 是配置解析后的快照文件路径。\n'
        '    输出：供监控页面显示的来源状态。\n'
        '    """\n'
        '    return {}\n',
        encoding="utf-8",
    )
    assert source in CODE_COMMENTS.python_targets(tmp_path)
    assert CODE_COMMENTS.definition_errors(source, tmp_path) == []
    source.write_text('def load(path):\n    """处理：读取监控快照。"""\n', encoding="utf-8")
    errors = CODE_COMMENTS.definition_errors(source, tmp_path)
    assert any("missing 输入：" in error for error in errors)
    assert any("missing 输出：" in error for error in errors)
