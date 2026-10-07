from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def origin_guard(
    allowed_origins: set[str],
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """CSRF defence alongside SameSite=Lax: reject state-changing browser requests whose
    Origin is not the frontend. Requests without an Origin header (non-browser clients)
    pass; they cannot carry a victim's cookie cross-site."""

    async def middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        if request.method in _UNSAFE_METHODS and origin and origin not in allowed_origins:
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        return await call_next(request)

    return middleware


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's default 422 body echoes the submitted input, which would leak passwords
    and API keys. Return only the location, message and type of each error."""
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [
        {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)
