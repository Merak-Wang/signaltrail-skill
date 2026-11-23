"""把完整模型输入按实际 token 顺序切块，绕过宿主单次回执截断。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import tiktoken

from .utils import read_json, write_json, write_text_atomic


def materialize_input_parts(input_file: Path, *, split_input: bool = True) -> dict:
    """处理：将完整输入切为至多七千五百 token 的有序 UTF-8 文本块。
    输入：已冻结的模型输入；工具读取宿主使用分块，直送宿主读取整份文件。
    输出：完整文件的身份、大小和 token 数；按需附可还原原文的工具读取分块。
    """
    input_file = input_file.resolve()
    source = input_file.read_bytes()
    input_hash = sha256(source).hexdigest()
    parent = input_file.parent
    base = parent if parent.name == "author-inputs" else parent / "author-inputs"
    directory = base / (input_file.stem + "-parts") / input_hash[:16]
    manifest = directory / "parts.json"
    if split_input and manifest.is_file():
        cached = read_json(manifest)
        if cached.get("input_sha256") == input_hash:
            return cached
    text = source.decode("utf-8")
    encoding = tiktoken.get_encoding("o200k_base")
    tokens = encoding.encode(text, disallowed_special=())
    result = {"input_file": str(input_file), "input_bytes": len(source),
              "input_sha256": input_hash, "input_tokens": len(tokens)}
    if not split_input:
        return result
    directory.mkdir(parents=True, exist_ok=True)
    parts, counts = [], []
    start = 0
    while start < len(tokens):
        end = min(start + 7500, len(tokens))
        while True:
            try:
                part = encoding.decode_bytes(tokens[start:end]).decode("utf-8")
            except UnicodeDecodeError:
                # token 边界可能落在一个汉字的字节内，缩短到完整字符再保存。
                end -= 1
                continue
            count = len(encoding.encode(part, disallowed_special=()))
            if count <= 7500:
                break
            end -= 1
        filename = f"part-{len(parts) + 1:03}.txt"
        write_text_atomic(directory / filename, part)
        parts.append(filename)
        counts.append(count)
        start = end
    result.update(input_parts_dir=str(directory), input_parts=parts,
                  input_part_tokens=counts, read_max_output_tokens=9000, reader_instruction=(
                  "Read every input_parts filename under input_parts_dir in listed order, "
                  "one part per tool result; do not combine outputs. Together they are the "
                  "complete input_file. Keep all parts in context before writing or reviewing. "
                  "Do not read the large input_file or invent another splitting method."))
    write_json(manifest, result)
    return result
