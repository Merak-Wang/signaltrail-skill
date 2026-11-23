"""提取日本银行拆借统计表中已公布的单元格。"""

from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from .content_extraction import ExtractedDocument, input_fingerprint
from .models import ContentStatus

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def extract_boj_table(content: bytes, url: str, *, truncated: bool) -> ExtractedDocument:
    """处理：按行读取统计表首张工作表的标题、单位及公开数据，保留原始列位置。
    输入：已限长的 XLSX 字节、原文地址和截断标记。
    输出：可供摘要的部分表格证据，无法解析时仅保留元数据。
    """
    document = ExtractedDocument(
        status=ContentStatus.METADATA_ONLY,
        quality={"extractor": "boj_xlsx", "extraction_status": "partial",
                 "completeness_basis": "published_table_cells"},
        provenance=input_fingerprint(content, "http_boj_xlsx_bytes", truncated=truncated),
        source_metadata={"url": url, "mime_type": _MIME},
    )
    if truncated:
        return document
    try:
        with ZipFile(BytesIO(content)) as archive:
            shared_path = "xl/sharedStrings.xml"
            sheet_path = "xl/worksheets/sheet1.xml"
            paths = [sheet_path]
            if shared_path in archive.namelist():
                paths.append(shared_path)
            if any(archive.getinfo(path).file_size > 512_000 for path in paths):
                return document
            roots = [ElementTree.fromstring(archive.read(path)) for path in paths]
        strings = ["".join(node.text or "" for node in item.iter(_NS + "t"))
                   for item in roots[1]] if len(roots) == 2 else []
        rows = []
        for row in roots[0].iter(_NS + "row"):
            values = []
            for cell in row.findall(_NS + "c"):
                text = cell.findtext(_NS + "v") or ""
                cell_type = cell.get("t")
                if cell_type == "s":
                    text = strings[int(text)]
                elif cell_type == "inlineStr":
                    text = "".join(node.text or "" for node in cell.iter(_NS + "t"))
                if text:
                    values.append(f"{cell.get('r', '')} {' '.join(text.split())}")
            if values:
                rows.append(" | ".join(values))
    except (BadZipFile, ElementTree.ParseError, KeyError, IndexError, ValueError):
        return document
    document.text = "\n".join(rows)
    if document.text:
        document.status = ContentStatus.PARTIAL
        document.blocks.append({"block_id": "table-1", "type": "paragraph", "text": document.text})
        document.quality["characters"] = len(document.text)
    return document
