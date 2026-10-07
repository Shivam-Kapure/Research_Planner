"""Page-aware text extraction from untrusted PDF bytes with pypdf (no OCR)."""

import asyncio
import io
from dataclasses import dataclass, field

from anyio import to_thread
from pypdf import PasswordType, PdfReader

from app.tools.documents.models import PageText
from app.tools.errors import InvalidPdf, PdfExtractionFailed, ToolError


@dataclass(frozen=True)
class ExtractionLimits:
    max_pages: int = 40  # architecture §8
    max_chars_per_page: int = 8_000
    max_total_chars: int = 120_000  # agents then read a ~16k-char excerpt (DocumentResult.excerpt)
    min_chars_per_page: int = 200  # below this on average the PDF is treated as scanned
    timeout_s: float = 20.0


@dataclass(frozen=True)
class ExtractedText:
    page_count: int
    pages: list[PageText] = field(default_factory=list)
    truncated: bool = False

    def is_sparse(self, min_chars_per_page: int) -> bool:
        """Too little text to be a text PDF (e.g. a scan); the caller falls back to the abstract."""
        pages_read = max(1, len(self.pages))
        total = sum(len(p.text) for p in self.pages)
        return total / pages_read < min_chars_per_page


async def extract_pdf_text(data: bytes, limits: ExtractionLimits | None = None) -> ExtractedText:
    """Runs pypdf in a worker thread with a deadline, so a pathological PDF cannot stall the
    event loop. pypdf's own decompression limits guard against compression bombs."""
    limits = limits or ExtractionLimits()
    failure: ToolError
    try:
        async with asyncio.timeout(limits.timeout_s):
            return await to_thread.run_sync(_extract, data, limits, abandon_on_cancel=True)
    except TimeoutError:
        failure = PdfExtractionFailed("pdf", f"text extraction exceeded {limits.timeout_s:g}s")
    raise failure


def _extract(data: bytes, limits: ExtractionLimits) -> ExtractedText:
    failure: ToolError
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            failure = InvalidPdf("pdf", "PDF is encrypted")
        else:
            page_count = len(reader.pages)
            return _read_pages(reader, page_count, limits)
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001 - malformed input can raise almost anything
        failure = InvalidPdf("pdf", f"PDF could not be parsed ({type(exc).__name__})")
    raise failure


def _read_pages(reader: PdfReader, page_count: int, limits: ExtractionLimits) -> ExtractedText:
    pages: list[PageText] = []
    total = 0
    failed = 0
    truncated = page_count > limits.max_pages
    for number in range(1, min(page_count, limits.max_pages) + 1):
        try:
            raw = reader.pages[number - 1].extract_text() or ""
        except Exception:  # noqa: BLE001 - skip an unreadable page, keep the rest
            failed += 1
            continue
        lines = (" ".join(line.split()) for line in raw.replace("\x00", "").splitlines())
        text = "\n".join(line for line in lines if line)
        if len(text) > limits.max_chars_per_page:
            text, truncated = text[: limits.max_chars_per_page], True
        if total + len(text) > limits.max_total_chars:
            text, truncated = text[: limits.max_total_chars - total], True
        if text:
            pages.append(PageText(page_number=number, text=text))
            total += len(text)
        if total >= limits.max_total_chars:
            break
    if failed and not pages:
        raise PdfExtractionFailed("pdf", f"text extraction failed on all {failed} pages")
    return ExtractedText(page_count=page_count, pages=pages, truncated=truncated)
