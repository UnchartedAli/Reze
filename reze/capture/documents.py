"""Document Intelligence: local text extraction and indexing.

Supported without extra dependencies: text, Markdown, CSV, JSON, logs, HTML
and DOCX (DOCX is a ZIP of XML, read with the standard library). PDF support is
optional and reported as unavailable when no PDF library is installed — the
command never pretends otherwise.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

from reze.database import db
from reze.search import universal

MAX_CHARS = 200_000
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".yaml", ".yml", ".ini", ".py", ".js", ".ts", ".html", ".htm", ".xml"}
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


class UnsupportedDocument(Exception):
    """Raised when the format cannot be read on this installation."""


def pdf_available() -> bool:
    try:
        import pypdf  # noqa: F401

        return True
    except ImportError:
        try:
            import PyPDF2  # noqa: F401

            return True
        except ImportError:
            return False


def extract(name: str, payload: bytes) -> Tuple[str, str]:
    """Return ``(kind, text)`` for one document payload."""
    extension = os.path.splitext(name or "")[1].lower()
    if extension == ".docx":
        return "docx", _extract_docx(payload)
    if extension == ".pdf":
        return "pdf", _extract_pdf(payload)
    if extension in {".html", ".htm"}:
        return "html", _strip_html(payload.decode("utf-8", errors="replace"))
    if extension in TEXT_EXTENSIONS or not extension:
        text = payload.decode("utf-8", errors="replace")
        if extension == ".json":
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except ValueError:
                pass
        return "text", text
    raise UnsupportedDocument(f"Unsupported document type: {extension or 'unknown'}")


def _extract_docx(payload: bytes) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
        xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise UnsupportedDocument("This file is not a valid DOCX document.") from exc
    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    parts = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
        if text.strip():
            parts.append(text)
    if not parts:
        raise UnsupportedDocument("The DOCX document contains no readable text.")
    return "\n".join(parts)


def _extract_pdf(payload: bytes) -> str:
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(payload))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except ImportError:
        pass
    try:
        import PyPDF2

        reader = PyPDF2.PdfReader(io.BytesIO(payload))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except ImportError as exc:
        raise UnsupportedDocument(
            "PDF extraction needs the optional 'pypdf' package (pip install pypdf)."
        ) from exc


def _strip_html(markup: str) -> str:
    cleaned = _TAG_RE.sub(" ", markup or "")
    cleaned = _ANY_TAG_RE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", html.unescape(cleaned)).strip()


class DocumentService:
    def store(self, name: str, text: str, source: str = "reply", summary: str = "", kind: str = "text") -> int:
        content = (text or "").strip()
        if not content:
            raise ValueError("The document contains no extractable text.")
        content = content[:MAX_CHARS]
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = db.query_one("SELECT * FROM documents WHERE content_hash = ?", (digest,))
        if existing:
            return int(existing["id"])
        document_id = db.execute(
            "INSERT INTO documents (name, kind, chars, summary, content_hash, source) VALUES (?, ?, ?, ?, ?, ?)",
            (
                (name or "document")[:200],
                (kind or "text")[:20],
                len(content),
                (summary or "")[:4000],
                digest,
                (source or "reply")[:40],
            ),
        )
        universal.index("document", document_id, name[:80], f"{content[:5000]} {summary}", kind)
        return document_id

    def get(self, document_id: int) -> Optional[Dict[str, Any]]:
        return db.query_one("SELECT * FROM documents WHERE id = ?", (int(document_id),))

    def list(self, limit: int = 20) -> List[Dict[str, Any]]:
        return db.query("SELECT * FROM documents ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 100)),))

    def delete(self, document_id: int) -> bool:
        db.execute("DELETE FROM documents WHERE id = ?", (int(document_id),))
        universal.unindex("document", document_id)
        return True

    def count(self) -> int:
        row = db.query_one("SELECT COUNT(*) AS total FROM documents")
        return int((row or {}).get("total") or 0)


document_service = DocumentService()

__all__ = [
    "DocumentService",
    "UnsupportedDocument",
    "document_service",
    "extract",
    "pdf_available",
]
