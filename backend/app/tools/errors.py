"""Tool-level errors for the literature and document tools.

Messages are composed here from status codes and hostnames only: they never contain API keys,
query strings, request headers or response bodies.
"""


class ToolError(Exception):
    code = "tool_error"
    retryable = False

    def __init__(self, source: str | None, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.source = source
        self.message = message
        self.http_status = http_status

    def __repr__(self) -> str:
        return f"{type(self).__name__}(source={self.source!r}, code={self.code!r})"


# ---- academic search providers ----


class SourceUnavailable(ToolError):
    code = "source_unavailable"
    retryable = True


class SourceTimeout(ToolError):
    code = "timeout"
    retryable = True


class SourceRateLimited(ToolError):
    code = "rate_limited"
    retryable = True

    def __init__(self, source: str | None, message: str, *, retry_after_s: float | None = None):
        super().__init__(source, message, http_status=429)
        self.retry_after_s = retry_after_s


class InvalidToolRequest(ToolError):
    code = "invalid_request"


class MalformedSourceResponse(ToolError):
    code = "malformed_response"


class LiteratureUnavailable(ToolError):
    """Every requested literature source failed (architecture: LITERATURE_UNAVAILABLE)."""

    code = "literature_unavailable"


# ---- documents ----


class NoOpenAccessFullText(ToolError):
    code = "no_oa_full_text"


class DownloadBlocked(ToolError):
    """The URL is not allowed (scheme, credentials, port, or a private/internal destination)."""

    code = "url_not_allowed"


class DownloadTimeout(ToolError):
    code = "download_timeout"


class DownloadFailed(ToolError):
    code = "download_failed"


class PdfTooLarge(ToolError):
    code = "pdf_too_large"


class InvalidPdf(ToolError):
    code = "invalid_pdf"


class PdfExtractionFailed(ToolError):
    code = "extraction_error"
