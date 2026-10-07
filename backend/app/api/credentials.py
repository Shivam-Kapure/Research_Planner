from fastapi import APIRouter, HTTPException, status

from app.api.deps import CredentialServiceDep, CurrentUser
from app.db.models import ProviderCredential
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
    provider: Provider, body: CredentialIn, user: CurrentUser, service: CredentialServiceDep
) -> CredentialStatus:
    credential = await service.save(user.id, provider.value, body.api_key.get_secret_value())
    return _status(provider, credential)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    provider: Provider, user: CurrentUser, service: CredentialServiceDep
) -> None:
    if not await service.delete(user.id, provider.value):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Credential not configured")
