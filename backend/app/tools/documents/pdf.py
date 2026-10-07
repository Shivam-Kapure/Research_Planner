"""Safe retrieval of untrusted, externally hosted PDFs.

Every URL (including each redirect target) must be http(s) on the default port, carry no
credentials, and resolve only to public IP addresses. The body is streamed with a hard size
cap and must start like a PDF. Nothing is written to disk and nothing is executed.

Known limit: the DNS check and the connection are separate lookups, so a hostile DNS server
could rebind between them; this blocks obvious SSRF (internal names, private/loopback/
link-local/metadata addresses) but is not a network-level egress firewall.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx2

from app.tools.errors import (
    DownloadBlocked,
    DownloadFailed,
    DownloadTimeout,
    InvalidPdf,
    PdfTooLarge,
    ToolError,
)

MAX_PDF_BYTES = 15 * 1024 * 1024
PDF_MAGIC = b"%PDF-"
_MAGIC_WINDOW = 1024  # the PDF header may appear anywhere in the first 1024 bytes
_REDIRECTS = {301, 302, 303, 307, 308}
_PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
    "binary/octet-stream",
}
_BLOCKED_HOSTS = {"localhost", "metadata", "metadata.google.internal", "instance-data"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa", ".lan")

Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


@dataclass(frozen=True)
class PdfLimits:
    max_bytes: int = MAX_PDF_BYTES
    timeout_s: float = 30.0  # whole download, redirects included
    max_redirects: int = 3


@dataclass(frozen=True)
class FetchedPdf:
    data: bytes
    host: str  # final host after redirects
    redirects: int


class SafePdfFetcher:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        limits: PdfLimits | None = None,
        resolver: Resolver = system_resolver,
    ) -> None:
        self._client = client
        self._limits = limits or PdfLimits()
        self._resolver = resolver

    async def fetch(self, url: str) -> FetchedPdf:
        failure: ToolError
        try:
            async with asyncio.timeout(self._limits.timeout_s):
                return await self._fetch(url)
        except (TimeoutError, httpx2.TimeoutException):
            failure = DownloadTimeout("pdf", f"PDF download exceeded {self._limits.timeout_s:g}s")
        except httpx2.TransportError as exc:
            failure = DownloadFailed("pdf", f"PDF connection failed ({type(exc).__name__})")
        raise failure

    async def _fetch(self, url: str) -> FetchedPdf:
        current = url
        previous_scheme: str | None = None
        for redirects in range(self._limits.max_redirects + 1):
            target = await self._checked(current, previous_scheme)
            async with self._client.stream(
                "GET",
                target,
                follow_redirects=False,  # every hop is validated here instead
                headers={"Accept": "application/pdf"},
            ) as response:
                status = response.status_code
                if status in _REDIRECTS:
                    location = response.headers.get("location")
                    if not location:
                        raise DownloadFailed("pdf", f"redirect without location from {target.host}")
                    current = str(target.join(location))
                    previous_scheme = target.scheme
                    continue
                if status >= 400:
                    raise DownloadFailed(
                        "pdf", f"HTTP {status} from {target.host}", http_status=status
                    )
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if content_type and content_type.lower() not in _PDF_CONTENT_TYPES:
                    raise InvalidPdf("pdf", f"{target.host} served {content_type[:60]}, not a PDF")
                data = await self._read_pdf(response, target.host)
                return FetchedPdf(data=data, host=target.host, redirects=redirects)
        raise DownloadFailed("pdf", f"more than {self._limits.max_redirects} redirects")

    async def _read_pdf(self, response: httpx2.Response, host: str) -> bytes:
        limit = self._limits.max_bytes
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise PdfTooLarge(
                "pdf", f"PDF from {host} declares {int(declared)} bytes (limit {limit})"
            )
        buffer = bytearray()
        async for chunk in response.aiter_bytes():
            buffer.extend(chunk)
            if len(buffer) > limit:
                raise PdfTooLarge("pdf", f"PDF from {host} exceeds {limit} bytes")
            if len(buffer) >= _MAGIC_WINDOW and PDF_MAGIC not in buffer[:_MAGIC_WINDOW]:
                raise InvalidPdf("pdf", f"{host} returned data that is not a PDF")
        if PDF_MAGIC not in buffer[:_MAGIC_WINDOW]:
            raise InvalidPdf("pdf", f"{host} returned data that is not a PDF")
        return bytes(buffer)

    async def _checked(self, url: str, previous_scheme: str | None) -> httpx2.URL:
        try:
            parsed = httpx2.URL(url)
        except Exception:  # noqa: BLE001 - any parse failure means "not allowed"
            raise DownloadBlocked("pdf", "malformed URL") from None
        if parsed.scheme not in ("https", "http"):
            raise DownloadBlocked("pdf", f"scheme {parsed.scheme!r} is not allowed")
        if previous_scheme == "https" and parsed.scheme == "http":
            raise DownloadBlocked("pdf", "redirect from https to http is not allowed")
        if parsed.userinfo:
            raise DownloadBlocked("pdf", "URLs with embedded credentials are not allowed")
        if parsed.port not in (None, 80, 443):
            raise DownloadBlocked("pdf", "only the default http/https ports are allowed")
        host = parsed.host.lower().rstrip(".")
        if not host:
            raise DownloadBlocked("pdf", "URL has no host")
        port = 443 if parsed.scheme == "https" else 80

        literal = _ip_or_none(host)
        if literal is None and (
            host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES) or "." not in host
        ):
            raise DownloadBlocked("pdf", f"internal host {host!r} is not allowed")
        addresses = [host] if literal is not None else await self._resolve(host, port)
        for address in addresses:
            if not _is_public(address):
                raise DownloadBlocked("pdf", f"{host!r} resolves to a non-public address")
        return parsed

    async def _resolve(self, host: str, port: int) -> list[str]:
        failure: ToolError
        try:
            addresses = await self._resolver(host, port)
        except OSError:
            failure = DownloadFailed("pdf", f"could not resolve {host!r}")
        else:
            if addresses:
                return addresses
            failure = DownloadFailed("pdf", f"{host!r} has no addresses")
        raise failure


def _ip_or_none(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return None


def _is_public(address: str) -> bool:
    ip = _ip_or_none(address.split("%", 1)[0])  # drop IPv6 zone ids
    if ip is None:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # is_global excludes private, loopback, link-local (incl. 169.254.169.254), CGNAT,
    # unspecified and reserved ranges.
    return ip.is_global and not ip.is_multicast
