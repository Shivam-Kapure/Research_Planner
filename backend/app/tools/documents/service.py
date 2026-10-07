"""paper → bounded, page-aware document (or an explicit abstract-only/unavailable result)."""

from app.schemas.contracts.analysis import FailureReason
from app.tools.documents.extraction import ExtractionLimits, extract_pdf_text
from app.tools.documents.models import DocumentResult
from app.tools.documents.oa import open_access_pdf_url
from app.tools.documents.pdf import SafePdfFetcher
from app.tools.errors import InvalidPdf, PdfExtractionFailed, PdfTooLarge, ToolError
from app.tools.literature.models import Paper


async def retrieve_document(
    paper: Paper,
    *,
    fetcher: SafePdfFetcher,
    limits: ExtractionLimits | None = None,
) -> DocumentResult:
    """Never raises for document problems: every failure becomes a structured fallback that
    names the reason, so one bad PDF cannot fail a research run."""
    limits = limits or ExtractionLimits()
    url = open_access_pdf_url(paper)
    reason: FailureReason
    error: ToolError | None = None
    host: str | None = None

    if url is None:
        reason = "no_oa_pdf"
    else:
        try:
            fetched = await fetcher.fetch(url)
            host = fetched.host
            text = await extract_pdf_text(fetched.data, limits)
        except ToolError as exc:
            error = exc
            reason = _reason_for(exc)
        else:
            if not text.is_sparse(limits.min_chars_per_page):
                return DocumentResult(
                    paper_key=paper.paper_key,
                    mode="full_text",
                    pages=text.pages,
                    page_count=text.page_count,
                    truncated=text.truncated,
                    abstract=paper.abstract,
                    source_host=host,
                )
            reason = "scanned_pdf"

    return DocumentResult(
        paper_key=paper.paper_key,
        mode="abstract_only" if paper.abstract else "unavailable",
        failure_reason=reason,
        error_code=error.code if error else None,
        detail=error.message[:300] if error else None,
        abstract=paper.abstract,
        source_host=host,
    )


def _reason_for(error: ToolError) -> FailureReason:
    if isinstance(error, PdfTooLarge):
        return "too_large"
    if isinstance(error, InvalidPdf):
        return "malformed_pdf"
    if isinstance(error, PdfExtractionFailed):
        return "extraction_error"
    return "download_failed"  # blocked URL, HTTP error, timeout, connection failure
