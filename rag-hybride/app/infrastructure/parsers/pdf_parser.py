import io
import statistics
from datetime import date
from typing import Any

import pdfplumber

from app.domain.chunking import RawSection
from app.domain.errors import UnparsableDocumentError
from app.domain.models import Document
from app.domain.versioning import make_document_id

HEADING_SIZE_RATIO = 1.15

# A PDF carries no frontmatter, so there is no version to read from it. Every
# ingested PDF is therefore version "1" and re-ingesting one updates that same
# version in place rather than creating a superseded row.
PDF_DEFAULT_VERSION = "1"


class PdfParser:
    def parse(
        self, raw_bytes: bytes, document_type: str, source_path: str
    ) -> tuple[Document, list[RawSection]]:
        sections: list[RawSection] = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            if not pdf.pages:
                raise UnparsableDocumentError(f"empty PDF: {source_path}")
            title = (pdf.metadata or {}).get("Title") or source_path
            for page in pdf.pages:
                for table in page.extract_tables():
                    rows = ["\t".join(cell or "" for cell in row) for row in table]
                    sections.append(RawSection(content="\n".join(rows), content_type="table"))
                sections.extend(_extract_text_sections(page))

        if not sections:
            raise UnparsableDocumentError(f"no extractable content in {source_path}")

        document = Document(
            id=make_document_id(source_path, document_type, PDF_DEFAULT_VERSION),
            title=title,
            product_ref=source_path,
            version=PDF_DEFAULT_VERSION,
            status="active",
            document_type=document_type,
            published_date=date.today(),
            source_path=source_path,
            content_hash="",
        )
        return document, sections


def _extract_text_sections(page) -> list[RawSection]:  # type: ignore[no-untyped-def]
    words = page.extract_words(extra_attrs=["size"])
    if not words:
        return []

    lines: dict[float, list[Any]] = {}
    for word in words:
        lines.setdefault(round(word["top"]), []).append(word)

    body_size = statistics.median(w["size"] for w in words)
    heading_threshold = body_size * HEADING_SIZE_RATIO

    sections: list[RawSection] = []
    buffer: list[str] = []
    for top in sorted(lines):
        line_words = sorted(lines[top], key=lambda w: w["x0"])
        line_text = " ".join(w["text"] for w in line_words)
        avg_size = statistics.mean(w["size"] for w in line_words)
        if avg_size >= heading_threshold and buffer:
            sections.append(RawSection(content="\n".join(buffer), content_type="text"))
            buffer = []
        buffer.append(line_text)
    if buffer:
        sections.append(RawSection(content="\n".join(buffer), content_type="text"))
    return sections
