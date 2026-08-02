from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class OidcSettings(Protocol):
    oidc_issuer: str | None
    oidc_audience: str | None
    oidc_introspection_endpoint: str | None
    oidc_introspection_client_id: str | None
    oidc_introspection_client_secret: str | None
    oidc_user_claim: str
    oidc_tenant_claim: str
    oidc_roles_claim: str
    oidc_admin_roles: tuple[str, ...]
    oidc_member_roles: tuple[str, ...]
    oidc_clock_skew_seconds: int
    oidc_http_timeout_seconds: int
    oidc_cache_seconds: int


@dataclass(frozen=True)
class VerifiedPrincipal:
    tenant_id: str
    user_id: str
    role: str


class AuthProviderError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_CACHE_LOCK = threading.RLock()
_CACHE: OrderedDict[
    str,
    tuple[float, Mapping[str, Any]],
] = OrderedDict()
_CACHE_MAX_ENTRIES = 2048


def _claim(
    claims: Mapping[str, Any],
    path: str,
) -> Any:
    current: Any = claims
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        normalized = value.replace(",", " ")
        return {
            item
            for item in normalized.split()
            if item
        }
    if isinstance(value, (list, tuple, set)):
        return {
            str(item).strip()
            for item in value
            if str(item).strip()
        }
    return set()


def _audience_matches(
    actual: Any,
    expected: str,
) -> bool:
    if isinstance(actual, str):
        return actual == expected
    if isinstance(actual, (list, tuple, set)):
        return expected in {
            str(item)
            for item in actual
        }
    return False


def map_introspection_claims(
    claims: Mapping[str, Any],
    settings: OidcSettings,
    *,
    now: float | None = None,
) -> VerifiedPrincipal:
    current_time = time.time() if now is None else now

    if claims.get("active") is not True:
        raise AuthProviderError(
            "AUTH_TOKEN_INACTIVE",
            "The access token is not active.",
            status_code=401,
        )

    issuer = str(claims.get("iss") or "").rstrip("/")
    if not settings.oidc_issuer or issuer != settings.oidc_issuer:
        raise AuthProviderError(
            "AUTH_TOKEN_ISSUER_INVALID",
            "The access token issuer is invalid.",
            status_code=401,
        )

    if (
        not settings.oidc_audience
        or not _audience_matches(
            claims.get("aud"),
            settings.oidc_audience,
        )
    ):
        raise AuthProviderError(
            "AUTH_TOKEN_AUDIENCE_INVALID",
            "The access token audience is invalid.",
            status_code=401,
        )

    try:
        expires_at = float(claims["exp"])
    except (KeyError, TypeError, ValueError):
        raise AuthProviderError(
            "AUTH_TOKEN_EXPIRATION_REQUIRED",
            "The access token expiration is missing.",
            status_code=401,
        ) from None

    if (
        expires_at
        + settings.oidc_clock_skew_seconds
        <= current_time
    ):
        raise AuthProviderError(
            "AUTH_TOKEN_EXPIRED",
            "The access token has expired.",
            status_code=401,
        )

    user_id = str(
        _claim(claims, settings.oidc_user_claim)
        or ""
    ).strip()
    tenant_id = str(
        _claim(claims, settings.oidc_tenant_claim)
        or ""
    ).strip()
    if not user_id or not tenant_id:
        raise AuthProviderError(
            "AUTH_MEMBERSHIP_CLAIMS_REQUIRED",
            "Verified user and tenant claims are required.",
            status_code=403,
        )

    roles = _string_set(
        _claim(claims, settings.oidc_roles_claim)
    )
    admin_roles = set(settings.oidc_admin_roles)
    member_roles = set(settings.oidc_member_roles)

    if roles & admin_roles:
        role = "admin"
    elif roles & member_roles:
        role = "member"
    else:
        raise AuthProviderError(
            "AUTH_ROLE_NOT_AUTHORIZED",
            "The verified identity has no ORKIO role.",
            status_code=403,
        )

    return VerifiedPrincipal(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
    )


def _token_key(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def _cache_get(
    token_key: str,
    *,
    now: float,
) -> Mapping[str, Any] | None:
    with _CACHE_LOCK:
        item = _CACHE.get(token_key)
        if item is None:
            return None
        valid_until, claims = item
        if valid_until <= now:
            _CACHE.pop(token_key, None)
            return None
        _CACHE.move_to_end(token_key)
        return claims


def _cache_set(
    token_key: str,
    claims: Mapping[str, Any],
    *,
    now: float,
    cache_seconds: int,
) -> None:
    if cache_seconds <= 0:
        return
    try:
        token_expiry = float(claims["exp"])
    except (KeyError, TypeError, ValueError):
        return
    valid_until = min(
        now + cache_seconds,
        token_expiry,
    )
    if valid_until <= now:
        return
    with _CACHE_LOCK:
        _CACHE[token_key] = (
            valid_until,
            dict(claims),
        )
        _CACHE.move_to_end(token_key)
        while len(_CACHE) > _CACHE_MAX_ENTRIES:
            _CACHE.popitem(last=False)


def clear_introspection_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def introspect_token(
    token: str,
    settings: OidcSettings,
    *,
    opener: Any = urllib.request.urlopen,
    now: float | None = None,
) -> Mapping[str, Any]:
    current_time = time.time() if now is None else now
    key = _token_key(token)
    cached = _cache_get(key, now=current_time)
    if cached is not None:
        return cached

    endpoint = settings.oidc_introspection_endpoint
    client_id = settings.oidc_introspection_client_id
    client_secret = (
        settings.oidc_introspection_client_secret
    )
    if not endpoint or not client_id or not client_secret:
        raise AuthProviderError(
            "AUTH_PROVIDER_NOT_CONFIGURED",
            "The external authentication provider is not configured.",
            status_code=503,
        )

    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode("utf-8")
    ).decode("ascii")
    body = urllib.parse.urlencode(
        {
            "token": token,
            "token_type_hint": "access_token",
        }
    ).encode("ascii")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
            "Accept": "application/json",
        },
    )

    try:
        with opener(
            request,
            timeout=settings.oidc_http_timeout_seconds,
        ) as response:
            raw = response.read(1024 * 1024)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as exc:
        raise AuthProviderError(
            "AUTH_PROVIDER_UNAVAILABLE",
            "The external authentication provider is unavailable.",
            status_code=503,
        ) from exc

    try:
        claims = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthProviderError(
            "AUTH_PROVIDER_RESPONSE_INVALID",
            "The authentication provider response is invalid.",
            status_code=503,
        ) from exc

    if not isinstance(claims, Mapping):
        raise AuthProviderError(
            "AUTH_PROVIDER_RESPONSE_INVALID",
            "The authentication provider response is invalid.",
            status_code=503,
        )

    _cache_set(
        key,
        claims,
        now=current_time,
        cache_seconds=settings.oidc_cache_seconds,
    )
    return claims


def verify_bearer_token(
    token: str,
    settings: OidcSettings,
    *,
    opener: Any = urllib.request.urlopen,
    now: float | None = None,
) -> VerifiedPrincipal:
    claims = introspect_token(
        token,
        settings,
        opener=opener,
        now=now,
    )
    return map_introspection_claims(
        claims,
        settings,
        now=now,
    )
