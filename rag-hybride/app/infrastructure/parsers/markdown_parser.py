import re
from datetime import date

import yaml  # type: ignore[import-untyped]

from app.domain.chunking import RawSection
from app.domain.errors import UnparsableDocumentError
from app.domain.models import Document
from app.domain.versioning import make_document_id

FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", re.DOTALL)
HEADER_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)


class MarkdownParser:
    def parse(
        self,
        raw_bytes: bytes,
        document_type: str,
        source_path: str,
    ) -> tuple[Document, list[RawSection]]:
        text = raw_bytes.decode("utf-8")
        match = FRONTMATTER_RE.match(text)
        if not match:
            raise UnparsableDocumentError(f"missing YAML frontmatter in {source_path}")

        metadata = yaml.safe_load(match.group(1))
        body = match.group(2)

        try:
            document = Document(
                id=make_document_id(
                    str(metadata["product_ref"]), document_type, str(metadata["version"])
                ),
                title=str(metadata["title"]),
                product_ref=str(metadata["product_ref"]),
                version=str(metadata["version"]),
                status="active",
                document_type=document_type,
                published_date=date.fromisoformat(str(metadata["published_date"])),
                source_path=source_path,
                content_hash="",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise UnparsableDocumentError(
                f"invalid or missing frontmatter field in {source_path}: {exc}"
            ) from exc
        return document, _split_into_sections(body)


def _split_into_sections(body: str) -> list[RawSection]:
    headers = list(HEADER_RE.finditer(body))
    if not headers:
        return _split_paragraphs(body)

    sections: list[RawSection] = []
    boundaries = [h.start() for h in headers] + [len(body)]
    for start, end in zip(boundaries, boundaries[1:]):
        block = body[start:end].strip()
        if block:
            sections.extend(_split_paragraphs(block))
    return sections


def _split_paragraphs(block: str) -> list[RawSection]:
    sections: list[RawSection] = []
    for paragraph in re.split(r"\n\s*\n", block.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        content_type = "table" if paragraph.lstrip().startswith("|") else "text"
        sections.append(RawSection(content=paragraph, content_type=content_type))
    return sections
