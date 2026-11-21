from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError
from pypdf import PdfReader

from app.core.arabic import normalize_arabic

MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_PDF_PAGES = 2500
DEFAULT_CHUNK_CHARS = 1800
DEFAULT_OVERLAP_CHARS = 180


class ManualIndexError(RuntimeError):
    """Raised when a manual cannot be indexed or its index is invalid."""


class ManualDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    title: str = Field(min_length=3, max_length=240)
    manufacturer: str = Field(min_length=2, max_length=120)
    equipment_models: list[str] = Field(default_factory=list)
    model_codes: list[str] = Field(default_factory=list)
    document_number: str | None = Field(default=None, max_length=120)
    revision: str | None = Field(default=None, max_length=80)
    language: str = Field(default="en", min_length=2, max_length=16)
    source_url: HttpUrl | None = None
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(ge=1)
    text_pages: int = Field(ge=0)
    pages_requiring_ocr: int = Field(ge=0)
    indexed_at: datetime
    rights_confirmed: bool
    rights_note: str = Field(min_length=8, max_length=1000)


class ManualChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=16, max_length=64)
    doc_id: str
    pdf_page_index: int = Field(ge=0)
    pdf_page_number: int = Field(ge=1)
    printed_page_number: int | None = Field(default=None, ge=1)
    chunk_index: int = Field(ge=0)
    section_title: str | None = Field(default=None, max_length=240)
    text: str = Field(min_length=20, max_length=DEFAULT_CHUNK_CHARS + 100)


class ManualIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    document: ManualDocument
    chunks: list[ManualChunk]


class ManualDocumentSummary(BaseModel):
    doc_id: str
    title: str
    manufacturer: str
    equipment_models: list[str]
    model_codes: list[str]
    document_number: str | None
    revision: str | None
    language: str
    page_count: int
    text_pages: int
    pages_requiring_ocr: int
    indexed_at: datetime
    source_url: str | None


class ManualSearchHit(BaseModel):
    document_id: str
    title: str
    manufacturer: str
    document_number: str | None
    revision: str | None
    pdf_page_index: int
    pdf_page_number: int
    printed_page_number: int | None
    section_title: str | None
    excerpt: str
    source_url: str | None
    score: float


class ManualSearchResponse(BaseModel):
    query: str
    equipment_model: str | None = None
    retrieval_method: str = "bm25_lexical"
    vector_search_enabled: bool = False
    hits: list[ManualSearchHit] = Field(default_factory=list)


def _terms(text: str) -> list[str]:
    normalized = normalize_arabic(text).lower()
    return re.findall(r"[a-z0-9]+|[\u0600-\u06ff]+", normalized)


def _printed_page_number(text: str) -> int | None:
    tail = text[-1200:]
    matches = re.findall(
        r"(?:page\s*(?:number\s*)?:?\s*)?(\d{1,4})\s*(?:/|of)\s*\d{1,4}",
        tail,
        flags=re.IGNORECASE,
    )
    if not matches:
        return None
    value = int(matches[-1])
    return value if value > 0 else None


def _section_title(text: str) -> str | None:
    for line in text.splitlines()[:8]:
        candidate = re.sub(r"\s+", " ", line).strip(" \t-•")
        if len(candidate) < 4 or len(candidate) > 240:
            continue
        if re.search(r"[A-Za-z\u0600-\u06ff]", candidate):
            return candidate
    return None


def _split_page(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + max_chars, len(cleaned))
        if end < len(cleaned):
            boundary = cleaned.rfind("\n", start + max_chars // 2, end)
            if boundary > start:
                end = boundary
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(cleaned):
            break
        next_start = max(start + 1, end - overlap_chars)
        start = next_start
    return chunks


def build_manual_index(
    pdf_path: Path | str,
    *,
    doc_id: str,
    title: str,
    manufacturer: str,
    equipment_models: list[str],
    model_codes: list[str] | None = None,
    document_number: str | None = None,
    revision: str | None = None,
    language: str = "en",
    source_url: str | None = None,
    rights_confirmed: bool = False,
    rights_note: str = "",
    max_chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> ManualIndex:
    path = Path(pdf_path)
    if not path.is_file():
        raise ManualIndexError(f"PDF file does not exist: {path}")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_PDF_BYTES:
        raise ManualIndexError(f"PDF size must be between 1 byte and {MAX_PDF_BYTES} bytes.")
    if not rights_confirmed:
        raise ManualIndexError(
            "Rights confirmation is required. Do not index or distribute a manual "
            "unless your licence or permission allows this processing."
        )
    if len(rights_note.strip()) < 8:
        raise ManualIndexError("A meaningful rights_note is required.")
    if max_chunk_chars < 300 or max_chunk_chars > 5000:
        raise ManualIndexError("max_chunk_chars must be between 300 and 5000.")
    if overlap_chars < 0 or overlap_chars >= max_chunk_chars // 2:
        raise ManualIndexError("overlap_chars must be non-negative and less than half the chunk size.")

    raw_pdf = path.read_bytes()
    digest = hashlib.sha256(raw_pdf).hexdigest()
    try:
        reader = PdfReader(path, strict=True)
    except Exception as exc:
        raise ManualIndexError(f"Unable to read PDF: {type(exc).__name__}") from exc

    if reader.is_encrypted:
        raise ManualIndexError("Encrypted PDFs are not indexed; provide an authorized unlocked copy.")
    page_count = len(reader.pages)
    if page_count < 1 or page_count > MAX_PDF_PAGES:
        raise ManualIndexError(f"PDF page count must be between 1 and {MAX_PDF_PAGES}.")

    chunks: list[ManualChunk] = []
    text_pages = 0
    pages_requiring_ocr = 0
    for page_index, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        page_text = page_text.strip()
        if len(page_text) < 20:
            pages_requiring_ocr += 1
            continue
        text_pages += 1
        section = _section_title(page_text)
        printed_page = _printed_page_number(page_text)
        for chunk_index, text_chunk in enumerate(
            _split_page(page_text, max_chunk_chars, overlap_chars)
        ):
            chunk_hash = hashlib.sha256(
                f"{doc_id}:{digest}:{page_index + 1}:{chunk_index}".encode("utf-8")
            ).hexdigest()
            chunks.append(
                ManualChunk(
                    chunk_id=chunk_hash,
                    doc_id=doc_id,
                    pdf_page_index=page_index,
                    pdf_page_number=page_index + 1,
                    printed_page_number=printed_page,
                    chunk_index=chunk_index,
                    section_title=section,
                    text=text_chunk,
                )
            )

    try:
        document = ManualDocument(
            doc_id=doc_id,
            title=title,
            manufacturer=manufacturer,
            equipment_models=equipment_models,
            model_codes=model_codes or [],
            document_number=document_number,
            revision=revision,
            language=language,
            source_url=source_url,
            sha256=digest,
            page_count=page_count,
            text_pages=text_pages,
            pages_requiring_ocr=pages_requiring_ocr,
            indexed_at=datetime.now(timezone.utc),
            rights_confirmed=rights_confirmed,
            rights_note=rights_note.strip(),
        )
    except ValidationError as exc:
        raise ManualIndexError(f"Invalid document metadata: {exc}") from exc

    if not chunks:
        raise ManualIndexError(
            "No extractable text was found. This PDF may be scanned; an authorized OCR "
            "workflow is required before it can be indexed."
        )
    return ManualIndex(document=document, chunks=chunks)


def write_manual_index(index: ManualIndex, index_dir: Path | str, overwrite: bool = False) -> Path:
    root = Path(index_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{index.document.doc_id}.json"
    if target.exists() and not overwrite:
        raise ManualIndexError(
            f"Index already exists: {target}. Use --overwrite only after reviewing it."
        )
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(index.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


@dataclass
class ManualLibrary:
    documents: dict[str, ManualDocument] = field(default_factory=dict)
    chunks: list[ManualChunk] = field(default_factory=list)

    @classmethod
    def load(cls, index_dir: Path | str) -> "ManualLibrary":
        root = Path(index_dir)
        library = cls()
        if not root.exists():
            return library
        for path in sorted(root.glob("*.json")):
            try:
                index = ManualIndex.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError) as exc:
                raise ManualIndexError(f"Invalid manual index {path.name}: {exc}") from exc
            if not index.document.rights_confirmed:
                raise ManualIndexError(
                    f"Manual index {path.name} has no confirmed rights status and was refused."
                )
            if index.document.doc_id in library.documents:
                raise ManualIndexError(f"Duplicate manual document id: {index.document.doc_id}")
            library.documents[index.document.doc_id] = index.document
            library.chunks.extend(index.chunks)
        return library

    def list_documents(self) -> list[ManualDocumentSummary]:
        return [
            ManualDocumentSummary(
                doc_id=document.doc_id,
                title=document.title,
                manufacturer=document.manufacturer,
                equipment_models=document.equipment_models,
                model_codes=document.model_codes,
                document_number=document.document_number,
                revision=document.revision,
                language=document.language,
                page_count=document.page_count,
                text_pages=document.text_pages,
                pages_requiring_ocr=document.pages_requiring_ocr,
                indexed_at=document.indexed_at,
                source_url=str(document.source_url) if document.source_url else None,
            )
            for document in sorted(self.documents.values(), key=lambda item: item.title.lower())
        ]

    def search(
        self,
        query: str,
        equipment_model: str | None = None,
        limit: int = 5,
    ) -> list[ManualSearchHit]:
        query_terms = _terms(query)
        if not query_terms or not self.chunks:
            return []
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")

        eligible: list[tuple[ManualChunk, ManualDocument, list[str]]] = []
        for chunk in self.chunks:
            document = self.documents.get(chunk.doc_id)
            if document is None:
                continue
            if equipment_model and equipment_model not in document.equipment_models:
                continue
            eligible.append((chunk, document, _terms(chunk.text)))
        if not eligible:
            return []

        document_frequency: dict[str, int] = {}
        for _, _, terms in eligible:
            for term in set(terms):
                document_frequency[term] = document_frequency.get(term, 0) + 1

        total = len(eligible)
        query_phrase = normalize_arabic(query).lower()
        hits: list[ManualSearchHit] = []
        for chunk, document, terms in eligible:
            term_counts: dict[str, int] = {}
            for term in terms:
                term_counts[term] = term_counts.get(term, 0) + 1

            score = 0.0
            for term in set(query_terms):
                tf = term_counts.get(term, 0)
                if tf == 0:
                    continue
                df = document_frequency.get(term, 0)
                inverse_frequency = math.log(1 + (total - df + 0.5) / (df + 0.5))
                score += inverse_frequency * ((tf * 2.2) / (tf + 1.2))
            normalized_chunk = normalize_arabic(chunk.text).lower()
            if query_phrase and len(query_phrase) >= 5 and query_phrase in normalized_chunk:
                score += 2.0
            if score <= 0:
                continue

            source_page = chunk.printed_page_number or chunk.pdf_page_number
            excerpt = chunk.text[:520].strip()
            hits.append(
                ManualSearchHit(
                    document_id=document.doc_id,
                    title=document.title,
                    manufacturer=document.manufacturer,
                    document_number=document.document_number,
                    revision=document.revision,
                    pdf_page_index=chunk.pdf_page_index,
                    pdf_page_number=chunk.pdf_page_number,
                    printed_page_number=chunk.printed_page_number,
                    section_title=chunk.section_title,
                    excerpt=excerpt,
                    source_url=str(document.source_url) if document.source_url else None,
                    score=round(score, 4),
                )
            )
        hits.sort(key=lambda item: (-item.score, item.document_id, item.pdf_page_number))
        return hits[:limit]
