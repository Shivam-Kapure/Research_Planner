import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError

from app.tools.documents.extraction import ExtractionLimits, extract_pdf_text
from app.tools.documents.models import DocumentResult, PageText
from app.tools.documents.oa import open_access_pdf_url
from app.tools.documents.pdf import MAX_PDF_BYTES, PdfLimits, SafePdfFetcher
from app.tools.documents.service import retrieve_document
from app.tools.errors import (
    DownloadBlocked,
    DownloadFailed,
    DownloadTimeout,
    InvalidPdf,
    PdfTooLarge,
)
from tests.fixtures.pdf.build_fixtures import build_pdf
from tests.llm_fakes import Recorder
from tests.tool_fakes import ChunkStream, make_resolver, paper, public_resolver

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures" / "pdf"
PAPER_PDF = (FIXTURES / "paper.pdf").read_bytes()
SCANNED_PDF = (FIXTURES / "scanned.pdf").read_bytes()
URL = "https://repo.example.org/papers/1.pdf"


def pdf_response(
    data: bytes = PAPER_PDF, content_type: str = "application/pdf", **kw: Any
) -> httpx2.Response:
    return httpx2.Response(200, content=data, headers={"content-type": content_type}, **kw)


def redirect(location: str, status: int = 302) -> httpx2.Response:
    return httpx2.Response(status, headers={"location": location})


def fetcher(recorder: Recorder, resolver: Any = public_resolver, **limits: Any) -> SafePdfFetcher:
    return SafePdfFetcher(recorder.client(), resolver=resolver, limits=PdfLimits(**limits))


# ---------------- download ----------------


async def test_valid_pdf_is_fetched() -> None:
    recorder = Recorder(pdf_response())
    result = await fetcher(recorder).fetch(URL)
    assert result.data == PAPER_PDF and result.host == "repo.example.org" and result.redirects == 0
    assert recorder.requests[0].headers["accept"] == "application/pdf"


@pytest.mark.parametrize(
    "content_type", ["application/octet-stream", "application/pdf; charset=binary", ""]
)
async def test_generic_or_missing_content_type_is_accepted_if_bytes_are_pdf(
    content_type: str,
) -> None:
    assert (
        await fetcher(Recorder(pdf_response(content_type=content_type))).fetch(URL)
    ).data == PAPER_PDF


@pytest.mark.parametrize(
    "response",
    [
        pdf_response(b"<html>Please log in to read this article</html>", content_type="text/html"),
        pdf_response(PAPER_PDF, content_type="text/html"),  # wrong declared type
        pdf_response(b"MZ\x90\x00 not a pdf" * 200, content_type="application/octet-stream"),
        pdf_response(b"short", content_type="application/pdf"),
    ],
    ids=["html-paywall", "wrong-type", "binary-not-pdf", "tiny-not-pdf"],
)
async def test_non_pdf_content_is_rejected(response: httpx2.Response) -> None:
    with pytest.raises(InvalidPdf):
        await fetcher(Recorder(response)).fetch(URL)


def test_size_limit_is_15_mb() -> None:
    assert MAX_PDF_BYTES == PdfLimits().max_bytes == 15 * 1024 * 1024


async def test_declared_oversize_is_rejected_before_reading() -> None:
    stream = ChunkStream(MAX_PDF_BYTES + 1)
    response = httpx2.Response(
        200,
        stream=stream,
        headers={"content-type": "application/pdf", "content-length": str(MAX_PDF_BYTES + 1)},
    )
    with pytest.raises(PdfTooLarge):
        await fetcher(Recorder(response)).fetch(URL)
    assert stream.sent == 0  # nothing buffered


async def test_undeclared_oversize_stream_is_cut_off() -> None:
    stream = ChunkStream(MAX_PDF_BYTES * 4, chunk=1024 * 1024)
    response = httpx2.Response(200, stream=stream, headers={"content-type": "application/pdf"})
    with pytest.raises(PdfTooLarge):
        await fetcher(Recorder(response)).fetch(URL)
    assert stream.sent <= MAX_PDF_BYTES + 1024 * 1024  # stopped one chunk past the limit


async def test_non_pdf_stream_is_rejected_after_first_kilobyte() -> None:
    stream = ChunkStream(10 * 1024 * 1024, chunk=4096, prefix=b"<html>")
    response = httpx2.Response(
        200, stream=stream, headers={"content-type": "application/octet-stream"}
    )
    with pytest.raises(InvalidPdf):
        await fetcher(Recorder(response)).fetch(URL)
    assert stream.sent <= 4096


async def test_redirects_are_followed_and_revalidated() -> None:
    recorder = Recorder(
        redirect("/mirror/1.pdf", 301), redirect("https://cdn.example.net/1.pdf"), pdf_response()
    )
    result = await fetcher(recorder).fetch(URL)
    assert result.redirects == 2 and result.host == "cdn.example.net"
    assert [str(r.url) for r in recorder.requests] == [
        URL,
        "https://repo.example.org/mirror/1.pdf",
        "https://cdn.example.net/1.pdf",
    ]


async def test_excessive_redirects_fail() -> None:
    recorder = Recorder(*[redirect(f"https://repo.example.org/{i}.pdf") for i in range(4)])
    with pytest.raises(DownloadFailed, match="redirects"):
        await fetcher(recorder).fetch(URL)
    assert len(recorder.requests) == 4  # 1 + max_redirects (3)


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1/admin.pdf",
        "http://10.0.0.5/x.pdf",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/x.pdf",
        "https://internal.example.org/x.pdf",  # resolves to a private address
    ],
)
async def test_redirect_to_private_destination_is_blocked(target: str) -> None:
    resolver = make_resolver({"internal.example.org": ["192.168.1.20"]})
    recorder = Recorder(redirect(target))
    with pytest.raises(DownloadBlocked):
        await fetcher(recorder, resolver).fetch(URL)
    assert len(recorder.requests) == 1  # the blocked destination was never contacted


async def test_https_to_http_downgrade_is_blocked() -> None:
    recorder = Recorder(redirect("http://repo.example.org/1.pdf"))
    with pytest.raises(DownloadBlocked, match="https to http"):
        await fetcher(recorder).fetch(URL)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x.pdf",
        "http://LOCALHOST./x.pdf",
        "http://127.0.0.1/x.pdf",
        "http://0.0.0.0/x.pdf",
        "http://[::1]/x.pdf",
        "http://[::ffff:127.0.0.1]/x.pdf",
        "http://10.1.2.3/x.pdf",
        "http://172.16.0.1/x.pdf",
        "http://192.168.0.10/x.pdf",
        "http://100.64.0.1/x.pdf",
        "http://[fd00::1]/x.pdf",
        "http://[fe80::1]/x.pdf",
        "http://169.254.169.254/latest/meta-data/iam",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://intranet/x.pdf",
        "http://printer.local/x.pdf",
        "https://user:secret@repo.example.org/x.pdf",
        "https://repo.example.org:8443/x.pdf",
        "ftp://repo.example.org/x.pdf",
        "file:///etc/passwd",
        "https://rebound.example.org/x.pdf",  # public-looking name, loopback DNS answer
        "https://mixed.example.org/x.pdf",  # any private answer is enough to block
    ],
)
async def test_private_and_unsafe_destinations_are_blocked(url: str) -> None:
    resolver = make_resolver(
        {"rebound.example.org": ["127.0.0.1"], "mixed.example.org": ["93.184.215.14", "10.0.0.1"]}
    )
    recorder = Recorder()
    with pytest.raises(DownloadBlocked):
        await fetcher(recorder, resolver).fetch(url)
    assert recorder.requests == []  # rejected before any request


async def test_http_error_is_not_bypassed() -> None:
    with pytest.raises(DownloadFailed) as exc_info:
        await fetcher(Recorder(httpx2.Response(403))).fetch(URL)
    assert exc_info.value.http_status == 403


@pytest.mark.parametrize("error", [httpx2.ReadTimeout("slow"), httpx2.ConnectTimeout("slow")])
async def test_timeout(error: Exception) -> None:
    with pytest.raises(DownloadTimeout):
        await fetcher(Recorder(error)).fetch(URL)


async def test_signed_url_tokens_never_reach_logs_or_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    token = "X-Amz-Signature=TESTONLYsignature0123456789"
    with pytest.raises(DownloadFailed) as exc_info:
        await fetcher(Recorder(httpx2.Response(500))).fetch(f"{URL}?{token}")
    assert any("HTTP Request" in r.getMessage() for r in caplog.records)
    assert token not in caplog.text
    assert token not in str(exc_info.value) and "repo.example.org" in str(exc_info.value)
    assert exc_info.value.__context__ is None


# ---------------- extraction ----------------


async def test_page_aware_extraction_of_fixture() -> None:
    text = await extract_pdf_text(PAPER_PDF)
    assert text.page_count == 4 and [p.page_number for p in text.pages] == [1, 2, 3, 4]
    assert "Recall was 20% lower after a night without sleep" in text.pages[2].text
    assert text.pages[0].text.startswith("Sleep Deprivation and Memory Consolidation")
    assert not text.truncated and not text.is_sparse(200)


async def test_scanned_pdf_is_detected_as_sparse() -> None:
    text = await extract_pdf_text(SCANNED_PDF)
    assert text.page_count == 3 and text.pages == [] and text.is_sparse(200)


async def test_extraction_limits() -> None:
    by_pages = await extract_pdf_text(PAPER_PDF, ExtractionLimits(max_pages=2))
    assert [p.page_number for p in by_pages.pages] == [1, 2] and by_pages.truncated
    by_chars = await extract_pdf_text(PAPER_PDF, ExtractionLimits(max_total_chars=300))
    assert sum(len(p.text) for p in by_chars.pages) == 300 and by_chars.truncated


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.4\nthis is not really a pdf",
        PAPER_PDF[:200],
        b"%PDF-1.7\n" + bytes(range(256)) * 50,
    ],
    ids=["garbage", "truncated", "binary-noise"],
)
async def test_malformed_pdfs_fail_safely(data: bytes) -> None:
    with pytest.raises(InvalidPdf):
        await extract_pdf_text(data)


async def test_excerpt_respects_budget_and_drops_references() -> None:
    text = await extract_pdf_text(PAPER_PDF)
    doc = DocumentResult(paper_key="doi:x", mode="full_text", pages=text.pages, page_count=4)
    excerpt = doc.excerpt()
    assert [p.page_number for p in excerpt] == [1, 2, 3]  # page 4 is the reference list
    assert all("Neuropsychologia" not in p.text for p in excerpt)
    small = doc.excerpt(max_chars=250)
    assert sum(len(p.text) for p in small) == 250 and small[0].page_number == 1


def test_document_result_states_are_explicit() -> None:
    with pytest.raises(ValidationError):
        DocumentResult(paper_key="k", mode="full_text")  # no pages
    with pytest.raises(ValidationError):
        DocumentResult(
            paper_key="k", mode="abstract_only", failure_reason="no_oa_pdf"
        )  # no abstract
    with pytest.raises(ValidationError):
        DocumentResult(paper_key="k", mode="unavailable")  # no reason
    with pytest.raises(ValidationError):
        DocumentResult(
            paper_key="k",
            mode="unavailable",
            failure_reason="no_oa_pdf",
            pages=[PageText(page_number=1, text="x")],
        )


# ---------------- retrieval service (paper → document) ----------------


def with_pdf(**fields: Any) -> Any:
    return paper(
        oa_pdf_url=URL, is_open_access=True, abstract="Sleep loss lowers recall.", **fields
    )


async def test_full_text_retrieval() -> None:
    doc = await retrieve_document(with_pdf(doi="10.1/a"), fetcher=fetcher(Recorder(pdf_response())))
    assert doc.mode == "full_text" and doc.failure_reason is None
    assert doc.page_count == 4 and len(doc.pages) == 4 and doc.source_host == "repo.example.org"
    assert doc.paper_key == "doi:10.1/a"


async def test_no_open_access_url_falls_back_to_abstract() -> None:
    recorder = Recorder()
    closed = paper(
        abstract="Only the abstract is available.",
        landing_page_url="https://publisher.example/paywalled",
    )
    assert open_access_pdf_url(closed) is None
    doc = await retrieve_document(closed, fetcher=fetcher(recorder))
    assert (doc.mode, doc.failure_reason, doc.abstract) == (
        "abstract_only",
        "no_oa_pdf",
        "Only the abstract is available.",
    )
    assert recorder.requests == []  # landing pages are never fetched or scraped


async def test_unavailable_when_no_pdf_and_no_abstract() -> None:
    doc = await retrieve_document(paper(), fetcher=fetcher(Recorder()))
    assert (doc.mode, doc.failure_reason) == ("unavailable", "no_oa_pdf")


@pytest.mark.parametrize(
    ("response", "reason", "code"),
    [
        (httpx2.Response(403), "download_failed", "download_failed"),
        (httpx2.ReadTimeout("slow"), "download_failed", "download_timeout"),
        (
            pdf_response(b"<html>login</html>", content_type="text/html"),
            "malformed_pdf",
            "invalid_pdf",
        ),
        (pdf_response(b"%PDF-1.4\nbroken"), "malformed_pdf", "invalid_pdf"),
        (pdf_response(SCANNED_PDF), "scanned_pdf", None),
        (
            httpx2.Response(
                200,
                headers={
                    "content-type": "application/pdf",
                    "content-length": str(MAX_PDF_BYTES + 1),
                },
            ),
            "too_large",
            "pdf_too_large",
        ),
    ],
    ids=["forbidden", "timeout", "html", "corrupt", "scanned", "too-large"],
)
async def test_failures_fall_back_to_abstract_with_reason(
    response: Any, reason: str, code: str | None
) -> None:
    doc = await retrieve_document(with_pdf(), fetcher=fetcher(Recorder(response)))
    assert doc.mode == "abstract_only" and doc.failure_reason == reason and doc.error_code == code
    assert doc.abstract == "Sleep loss lowers recall." and doc.pages == []


async def test_blocked_url_falls_back_without_any_request() -> None:
    recorder = Recorder()
    doc = await retrieve_document(
        paper(oa_pdf_url="http://169.254.169.254/latest/meta-data", abstract="abs"),
        fetcher=fetcher(recorder),
    )
    assert (doc.failure_reason, doc.error_code) == ("download_failed", "url_not_allowed")
    assert recorder.requests == []


async def test_no_temporary_files_are_created(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("document tools must not create temporary files")

    for name in (
        "mkstemp",
        "mkdtemp",
        "NamedTemporaryFile",
        "TemporaryFile",
        "SpooledTemporaryFile",
    ):
        monkeypatch.setattr(tempfile, name, forbidden)
    doc = await retrieve_document(with_pdf(), fetcher=fetcher(Recorder(pdf_response())))
    assert doc.mode == "full_text"


async def test_generated_fixture_matches_committed_file() -> None:
    from tests.fixtures.pdf.build_fixtures import PAPER_PAGES

    assert build_pdf(PAPER_PAGES) == PAPER_PDF
