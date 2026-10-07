from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import (
    AuthServiceDep,
    CurrentUser,
    SettingsDep,
    clear_session_cookie,
    set_session_cookie,
)
from app.db.repositories.users import EmailAlreadyRegistered
from app.schemas.api.auth import LoginRequest, RegisterRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, auth: AuthServiceDep) -> UserOut:
    try:
        user = await auth.register(body.email, body.password.get_secret_value())
    except EmailAlreadyRegistered:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Registration failed") from None
    return UserOut.model_validate(user)


@router.post("/login")
async def login(
    body: LoginRequest, response: Response, auth: AuthServiceDep, settings: SettingsDep
) -> UserOut:
    user = await auth.authenticate(body.email, body.password.get_secret_value())
    if user is None:
        # Same response for unknown email and wrong password.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    session = await auth.start_session(user)
    set_session_cookie(response, settings, session.token)
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, auth: AuthServiceDep, settings: SettingsDep
) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await auth.revoke(token)
    clear_session_cookie(response, settings)


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
