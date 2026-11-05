"""有界文本 PDF 的部分证据提取。"""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .content_extraction import ExtractedDocument, input_fingerprint
from .models import ContentStatus


def extract_pdf(content: bytes, url: str, *, truncated: bool = False) -> ExtractedDocument:
    """处理：从 HTTP 已限长字节提取至多八十页文本，保留页码和出处。
    输入：公开 PDF 字节及原文 URL；不执行附件、脚本或 OCR。
    输出：部分证据文档；空白、加密或损坏文档保持元数据状态。
    """
    quality = {"extractor": "pypdf", "extraction_status": "partial",
               "completeness_basis": "pdf_text_only", "fact_verification": "not_performed",
               "response_truncated": truncated, "article_completeness": "unknown"}
    document = ExtractedDocument(
        status=ContentStatus.METADATA_ONLY, quality=quality,
        provenance=input_fingerprint(content, "http_pdf_bytes", truncated=truncated),
        source_metadata={"url": url, "mime_type": "application/pdf"},
    )
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            quality["pdf_error"] = "encrypted_pdf"
            return document
        quality["page_count"] = len(reader.pages)
        quality["page_limit_reached"] = len(reader.pages) > 80
        for page_number, page in enumerate(reader.pages[:80], 1):
            text = (page.extract_text() or "").strip()
            if text:
                document.blocks.append({"block_id": f"page-{page_number}", "type": "page",
                                        "page_number": page_number, "text": text})
    except (PdfReadError, ValueError) as exc:
        quality["pdf_error"] = type(exc).__name__
        return document
    document.text = "\n\n".join(
        f"[Page {block['page_number']}]\n{block['text']}" for block in document.blocks
    )
    quality["characters"] = len(document.text)
    quality["extracted_pages"] = len(document.blocks)
    if document.text:
        document.status = ContentStatus.PARTIAL
    else:
        quality["pdf_error"] = "no_text_layer"
    return document
