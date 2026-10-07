import httpx2
from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CredentialServiceDep, CurrentUser, SettingsDep
from app.db.models import ProviderCredential
from app.llm.key_check import check_provider_key
from app.schemas.api.credentials import CredentialIn, CredentialStatus, Provider

router = APIRouter(prefix="/credentials", tags=["credentials"])


def _status(provider: Provider, credential: ProviderCredential | None) -> CredentialStatus:
    if credential is None:
        return CredentialStatus(provider=provider, configured=False)
    return CredentialStatus(
        provider=provider,
        configured=True,
        key_hint=credential.key_hint,
        status=credential.status,
        validated_at=credential.validated_at,
        updated_at=credential.updated_at,
    )


@router.get("")
async def list_credentials(
    user: CurrentUser, service: CredentialServiceDep
) -> list[CredentialStatus]:
    stored = {c.provider: c for c in await service.list(user.id)}
    return [_status(p, stored.get(p.value)) for p in Provider]


@router.put("/{provider}")
async def save_credential(
    provider: Provider,
    body: CredentialIn,
    user: CurrentUser,
    service: CredentialServiceDep,
    settings: SettingsDep,
    request: Request,
) -> CredentialStatus:
    """Store the key encrypted, then (unless disabled) check it with one cheap call to the
    provider: status becomes valid, invalid or unverified (provider unreachable)."""
    api_key = body.api_key.get_secret_value()
    credential = await service.save(user.id, provider.value, api_key)
    if settings.validate_credentials_on_save:
        client: httpx2.AsyncClient = request.app.state.http_client
        result = await check_provider_key(client, provider.value, api_key)
        credential = await service.set_status(user.id, provider.value, result) or credential
    return _status(provider, credential)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    provider: Provider, user: CurrentUser, service: CredentialServiceDep
) -> None:
    if not await service.delete(user.id, provider.value):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Credential not configured")
