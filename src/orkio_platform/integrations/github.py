from __future__ import annotations

import base64
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping
from urllib.parse import quote

import httpx
import jwt

from orkio_platform.config import Settings


class GitHubConnectorError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 503,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    owner: str
    name: str

    @classmethod
    def parse(cls, value: str) -> "GitHubRepository":
        owner, separator, name = value.strip().partition("/")
        if (
            separator != "/"
            or not owner
            or not name
            or "/" in name
            or owner in {".", ".."}
            or name in {".", ".."}
        ):
            raise GitHubConnectorError(
                "GITHUB_REPOSITORY_INVALID",
                "The repository identifier is invalid.",
                status_code=400,
            )
        return cls(owner=owner, name=name)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True, slots=True)
class GitHubFileEvidence:
    repository: str
    ref: str
    commit_sha: str
    path: str
    blob_sha: str | None
    content: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class GitHubRepositoryEvidence:
    repository: str
    default_branch: str | None
    requested_ref: str
    commit_sha: str
    tree_sha: str
    tree_truncated: bool
    selected_files: tuple[GitHubFileEvidence, ...]


@dataclass(frozen=True, slots=True)
class GitHubConnectorStatus:
    enabled: bool
    configured: bool
    auth_mode: str
    read_only: bool
    auto_audit_enabled: bool
    allowed_repositories: tuple[str, ...]
    allowed_roles: tuple[str, ...]
    allowed_tenants_restricted: bool
    allowed_users_restricted: bool
    api_base_url: str
    api_version: str
    write_permissions: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "auth_mode": self.auth_mode,
            "read_only": self.read_only,
            "auto_audit_enabled": self.auto_audit_enabled,
            "allowed_repositories": list(self.allowed_repositories),
            "allowed_roles": list(self.allowed_roles),
            "allowed_tenants_restricted": (
                self.allowed_tenants_restricted
            ),
            "allowed_users_restricted": (
                self.allowed_users_restricted
            ),
            "api_base_url": self.api_base_url,
            "api_version": self.api_version,
            "write_permissions": self.write_permissions,
        }


class GitHubCredentialProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(
            timeout=settings.github_http_timeout_seconds,
            follow_redirects=False,
        )
        self._now = now or time.time
        self._lock = threading.RLock()
        self._cached_token: str | None = None
        self._cached_expiry: float = 0.0

    def _headers(
        self,
        *,
        bearer: str,
    ) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {bearer}",
            "X-GitHub-Api-Version": self._settings.github_api_version,
            "User-Agent": "ORKIO-GitHub-Readonly-Connector/1.0",
        }

    def _app_jwt(self) -> str:
        app_id = self._settings.github_app_id
        secret = self._settings.github_app_private_key_b64
        if not app_id or secret is None:
            raise GitHubConnectorError(
                "GITHUB_APP_CONFIGURATION_INCOMPLETE",
                "The GitHub App configuration is incomplete.",
            )
        try:
            private_key = base64.b64decode(
                secret.get_secret_value(),
                validate=True,
            )
        except Exception as exc:
            raise GitHubConnectorError(
                "GITHUB_APP_PRIVATE_KEY_INVALID",
                "The GitHub App private key is invalid.",
            ) from exc

        current = int(self._now())
        payload = {
            "iat": current - 60,
            "exp": current + 540,
            "iss": app_id,
        }
        try:
            encoded = jwt.encode(
                payload,
                private_key,
                algorithm="RS256",
            )
        except Exception as exc:
            raise GitHubConnectorError(
                "GITHUB_APP_JWT_FAILED",
                "The GitHub App could not sign an authentication token.",
            ) from exc
        return encoded.decode("ascii") if isinstance(encoded, bytes) else encoded

    @staticmethod
    def _parse_expiry(value: object) -> float:
        if not isinstance(value, str):
            return 0.0
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return 0.0

    def _installation_token(self) -> str:
        installation_id = self._settings.github_app_installation_id
        if installation_id is None:
            raise GitHubConnectorError(
                "GITHUB_APP_CONFIGURATION_INCOMPLETE",
                "The GitHub App installation ID is missing.",
            )

        current = self._now()
        with self._lock:
            if (
                self._cached_token
                and current < self._cached_expiry - 60
            ):
                return self._cached_token

            endpoint = (
                f"{self._settings.github_api_base_url}"
                f"/app/installations/{installation_id}/access_tokens"
            )
            try:
                response = self._client.post(
                    endpoint,
                    headers=self._headers(
                        bearer=self._app_jwt(),
                    ),
                    json={
                        "repositories": sorted(
                            {
                                GitHubRepository.parse(value).name
                                for value in (
                                    self._settings.github_allowed_repositories
                                )
                            }
                        ),
                        "permissions": {
                            "contents": "read",
                            "metadata": "read",
                        },
                    },
                )
            except httpx.TimeoutException as exc:
                raise GitHubConnectorError(
                    "GITHUB_AUTH_TIMEOUT",
                    "GitHub authentication timed out.",
                    retryable=True,
                ) from exc
            except httpx.HTTPError as exc:
                raise GitHubConnectorError(
                    "GITHUB_AUTH_UNAVAILABLE",
                    "GitHub authentication is unavailable.",
                    retryable=True,
                ) from exc

            if response.status_code not in {200, 201}:
                raise GitHubConnectorError(
                    "GITHUB_AUTH_REJECTED",
                    "GitHub rejected the App installation authentication.",
                    status_code=503,
                    retryable=response.status_code >= 500,
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise GitHubConnectorError(
                    "GITHUB_AUTH_RESPONSE_INVALID",
                    "GitHub returned an invalid authentication response.",
                ) from exc
            token = payload.get("token")
            if not isinstance(token, str) or not token:
                raise GitHubConnectorError(
                    "GITHUB_AUTH_RESPONSE_INVALID",
                    "GitHub returned no installation token.",
                )
            expiry = self._parse_expiry(payload.get("expires_at"))
            if expiry <= current:
                raise GitHubConnectorError(
                    "GITHUB_AUTH_RESPONSE_INVALID",
                    "GitHub returned an expired installation token.",
                )
            self._cached_token = token
            self._cached_expiry = expiry
            return token

    def token(self) -> str:
        if self._settings.github_auth_mode == "token":
            token = self._settings.github_token
            if token is None:
                raise GitHubConnectorError(
                    "GITHUB_TOKEN_REQUIRED",
                    "The GitHub token is not configured.",
                )
            return token.get_secret_value()
        if self._settings.github_auth_mode == "github_app":
            return self._installation_token()
        raise GitHubConnectorError(
            "GITHUB_AUTH_MODE_DISABLED",
            "GitHub authentication is disabled.",
        )


class GitHubReadOnlyClient:
    _SAFE_FILE_SUFFIXES = {
        ".c",
        ".cfg",
        ".conf",
        ".css",
        ".csv",
        ".go",
        ".graphql",
        ".h",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mjs",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
    _SAFE_FILE_NAMES = {
        "Dockerfile",
        "Procfile",
        "Makefile",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
    _DENIED_PATH_PARTS = {
        ".git",
        ".env",
        ".ssh",
        "credentials",
        "node_modules",
        "private_keys",
        "secrets",
        "vendor",
    }

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        credentials: GitHubCredentialProvider | None = None,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(
            timeout=settings.github_http_timeout_seconds,
            follow_redirects=False,
        )
        self._credentials = credentials or GitHubCredentialProvider(
            settings,
            client=self._client,
        )
        self._allowed = {
            value.casefold()
            for value in settings.github_allowed_repositories
        }

    def _ensure_enabled(self) -> None:
        if not self._settings.github_integration_enabled:
            raise GitHubConnectorError(
                "GITHUB_CONNECTOR_DISABLED",
                "The GitHub connector is disabled.",
            )
        if not self._settings.github_configured:
            raise GitHubConnectorError(
                "GITHUB_CONNECTOR_NOT_CONFIGURED",
                "The GitHub connector is not fully configured.",
            )
        if not self._settings.github_read_only:
            raise GitHubConnectorError(
                "GITHUB_READONLY_REQUIRED",
                "The GitHub connector must operate in read-only mode.",
            )

    def _ensure_allowed(
        self,
        repository: GitHubRepository,
    ) -> None:
        self._ensure_enabled()
        if repository.full_name.casefold() not in self._allowed:
            raise GitHubConnectorError(
                "GITHUB_REPOSITORY_NOT_ALLOWED",
                "The repository is not in the connector allowlist.",
                status_code=403,
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": (
                f"Bearer {self._credentials.token()}"
            ),
            "X-GitHub-Api-Version": self._settings.github_api_version,
            "User-Agent": "ORKIO-GitHub-Readonly-Connector/1.0",
        }

    @staticmethod
    def _map_response(
        response: httpx.Response,
    ) -> GitHubConnectorError:
        status_code = response.status_code
        rate_limit_remaining = response.headers.get(
            "X-RateLimit-Remaining"
        )
        retry_after = response.headers.get("Retry-After")
        if status_code in {403, 429} and (
            status_code == 429
            or rate_limit_remaining == "0"
            or retry_after is not None
        ):
            return GitHubConnectorError(
                "GITHUB_RATE_LIMITED",
                "The GitHub connector reached a rate limit.",
                status_code=503,
                retryable=True,
            )
        if status_code == 401:
            return GitHubConnectorError(
                "GITHUB_AUTH_REJECTED",
                "GitHub rejected the connector credentials.",
                status_code=503,
            )
        if status_code == 403:
            return GitHubConnectorError(
                "GITHUB_ACCESS_FORBIDDEN",
                "GitHub denied access to the requested repository resource.",
                status_code=403,
            )
        if status_code == 404:
            return GitHubConnectorError(
                "GITHUB_RESOURCE_NOT_FOUND",
                "The requested GitHub resource was not found.",
                status_code=404,
            )
        if status_code == 410:
            return GitHubConnectorError(
                "GITHUB_API_VERSION_UNSUPPORTED",
                "The configured GitHub REST API version is unsupported.",
                status_code=503,
            )
        if status_code in {409, 422}:
            return GitHubConnectorError(
                "GITHUB_REQUEST_INVALID",
                "GitHub could not process the read-only request.",
                status_code=502,
            )
        if status_code >= 500:
            return GitHubConnectorError(
                "GITHUB_UNAVAILABLE",
                "GitHub is temporarily unavailable.",
                retryable=True,
            )
        return GitHubConnectorError(
            "GITHUB_REQUEST_REJECTED",
            "GitHub rejected the read-only request.",
            status_code=502,
        )

    def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        self._ensure_enabled()
        endpoint = f"{self._settings.github_api_base_url}{path}"
        try:
            response = self._client.get(
                endpoint,
                headers=self._headers(),
                params=params,
            )
        except httpx.TimeoutException as exc:
            raise GitHubConnectorError(
                "GITHUB_REQUEST_TIMEOUT",
                "The GitHub read-only request timed out.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise GitHubConnectorError(
                "GITHUB_UNAVAILABLE",
                "GitHub is unavailable.",
                retryable=True,
            ) from exc
        if response.status_code != 200:
            raise self._map_response(response)
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = 0
            if (
                declared_length
                > self._settings.github_max_response_bytes
            ):
                raise GitHubConnectorError(
                    "GITHUB_RESPONSE_TOO_LARGE",
                    "GitHub returned a response above the configured limit.",
                    status_code=502,
                )
        if len(response.content) > self._settings.github_max_response_bytes:
            raise GitHubConnectorError(
                "GITHUB_RESPONSE_TOO_LARGE",
                "GitHub returned a response above the configured limit.",
                status_code=502,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitHubConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned an invalid response.",
            ) from exc
        if not isinstance(payload, Mapping):
            raise GitHubConnectorError(
                "GITHUB_RESPONSE_INVALID",
                "GitHub returned an invalid response shape.",
            )
        return payload

    @staticmethod
    def _repository_path(
        repository: GitHubRepository,
    ) -> str:
        owner = quote(repository.owner, safe="")
        name = quote(repository.name, safe="")
        return f"/repos/{owner}/{name}"

    def repository_metadata(
        self,
        repository_value: str,
    ) -> dict[str, object]:
        repository = GitHubRepository.parse(repository_value)
        self._ensure_allowed(repository)
        if not self._settings.github_allow_metadata_read:
            raise GitHubConnectorError(
                "GITHUB_METADATA_READ_DISABLED",
                "Repository metadata access is disabled.",
                status_code=403,
            )
        payload = self._get_json(
            self._repository_path(repository)
        )
        return {
            "full_name": payload.get("full_name"),
            "private": payload.get("private"),
            "default_branch": payload.get("default_branch"),
            "archived": payload.get("archived"),
            "disabled": payload.get("disabled"),
            "pushed_at": payload.get("pushed_at"),
            "updated_at": payload.get("updated_at"),
        }

    def resolve_ref(
        self,
        repository_value: str,
        ref: str,
    ) -> tuple[str, str]:
        repository = GitHubRepository.parse(repository_value)
        self._ensure_allowed(repository)
        if not ref or ".." in ref or any(
            character.isspace() for character in ref
        ):
            raise GitHubConnectorError(
                "GITHUB_REF_INVALID",
                "The GitHub reference is invalid.",
                status_code=400,
            )
        payload = self._get_json(
            f"{self._repository_path(repository)}"
            f"/commits/{quote(ref, safe='')}"
        )
        commit_sha = payload.get("sha")
        commit = payload.get("commit")
        tree_sha = (
            commit.get("tree", {}).get("sha")
            if isinstance(commit, Mapping)
            else None
        )
        if not isinstance(commit_sha, str) or not isinstance(tree_sha, str):
            raise GitHubConnectorError(
                "GITHUB_COMMIT_RESPONSE_INVALID",
                "GitHub returned invalid commit metadata.",
            )
        return commit_sha, tree_sha

    def tree(
        self,
        repository_value: str,
        tree_sha: str,
    ) -> tuple[tuple[dict[str, object], ...], bool]:
        repository = GitHubRepository.parse(repository_value)
        self._ensure_allowed(repository)
        payload = self._get_json(
            f"{self._repository_path(repository)}"
            f"/git/trees/{quote(tree_sha, safe='')}",
            params={"recursive": "1"},
        )
        raw_entries = payload.get("tree")
        if not isinstance(raw_entries, list):
            raise GitHubConnectorError(
                "GITHUB_TREE_RESPONSE_INVALID",
                "GitHub returned an invalid repository tree.",
            )
        entries: list[dict[str, object]] = []
        for item in raw_entries[
            : self._settings.github_max_tree_entries
        ]:
            if not isinstance(item, Mapping):
                continue
            path = item.get("path")
            item_type = item.get("type")
            if not isinstance(path, str) or item_type != "blob":
                continue
            entries.append(
                {
                    "path": path,
                    "sha": item.get("sha"),
                    "size": item.get("size"),
                }
            )
        truncated = bool(payload.get("truncated")) or (
            len(raw_entries)
            > self._settings.github_max_tree_entries
        )
        return tuple(entries), truncated

    @classmethod
    def path_is_readable(cls, path: str) -> bool:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts:
            return False
        lowered = {part.casefold() for part in pure.parts}
        if lowered & cls._DENIED_PATH_PARTS:
            return False
        if any(
            part.casefold().startswith(".env")
            for part in pure.parts
        ):
            return False
        name = pure.name
        suffix = pure.suffix.casefold()
        return (
            name in cls._SAFE_FILE_NAMES
            or suffix in cls._SAFE_FILE_SUFFIXES
        )

    def file_content(
        self,
        repository_value: str,
        *,
        commit_sha: str,
        path: str,
        blob_sha: str | None = None,
    ) -> GitHubFileEvidence:
        repository = GitHubRepository.parse(repository_value)
        self._ensure_allowed(repository)
        if not self._settings.github_allow_content_read:
            raise GitHubConnectorError(
                "GITHUB_CONTENT_READ_DISABLED",
                "Repository content access is disabled.",
                status_code=403,
            )
        if not self.path_is_readable(path):
            raise GitHubConnectorError(
                "GITHUB_PATH_NOT_ALLOWED",
                "The repository path is not allowed for content access.",
                status_code=403,
            )
        payload = self._get_json(
            f"{self._repository_path(repository)}"
            f"/contents/{quote(path, safe='/')}",
            params={"ref": commit_sha},
        )
        if payload.get("type") != "file":
            raise GitHubConnectorError(
                "GITHUB_CONTENT_NOT_FILE",
                "The requested repository content is not a file.",
                status_code=400,
            )
        size = payload.get("size")
        if (
            isinstance(size, int)
            and size > self._settings.github_max_file_bytes
        ):
            raise GitHubConnectorError(
                "GITHUB_FILE_TOO_LARGE",
                "The repository file exceeds the configured read limit.",
                status_code=413,
            )
        encoded = payload.get("content")
        encoding = payload.get("encoding")
        if not isinstance(encoded, str) or encoding != "base64":
            raise GitHubConnectorError(
                "GITHUB_CONTENT_RESPONSE_INVALID",
                "GitHub returned unsupported file content.",
            )
        try:
            raw = base64.b64decode(
                encoded.replace("\n", ""),
                validate=True,
            )
        except Exception as exc:
            raise GitHubConnectorError(
                "GITHUB_CONTENT_RESPONSE_INVALID",
                "GitHub returned invalid file content.",
            ) from exc
        if len(raw) > self._settings.github_max_file_bytes:
            raise GitHubConnectorError(
                "GITHUB_FILE_TOO_LARGE",
                "The repository file exceeds the configured read limit.",
                status_code=413,
            )
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitHubConnectorError(
                "GITHUB_FILE_NOT_TEXT",
                "The repository file is not UTF-8 text.",
                status_code=415,
            ) from exc
        return GitHubFileEvidence(
            repository=repository.full_name,
            ref=commit_sha,
            commit_sha=commit_sha,
            path=path,
            blob_sha=(
                blob_sha
                if isinstance(blob_sha, str)
                else payload.get("sha")
                if isinstance(payload.get("sha"), str)
                else None
            ),
            content=content,
            truncated=False,
        )

    def compare(
        self,
        repository_value: str,
        *,
        base: str,
        head: str,
    ) -> dict[str, object]:
        repository = GitHubRepository.parse(repository_value)
        self._ensure_allowed(repository)
        if not self._settings.github_allow_diff_read:
            raise GitHubConnectorError(
                "GITHUB_DIFF_READ_DISABLED",
                "Repository diff access is disabled.",
                status_code=403,
            )
        for value in (base, head):
            if not value or ".." in value or any(
                character.isspace() for character in value
            ):
                raise GitHubConnectorError(
                    "GITHUB_REF_INVALID",
                    "The GitHub reference is invalid.",
                    status_code=400,
                )
        payload = self._get_json(
            f"{self._repository_path(repository)}"
            f"/compare/{quote(base, safe='')}..."
            f"{quote(head, safe='')}"
        )
        files = payload.get("files")
        safe_files: list[dict[str, object]] = []
        if isinstance(files, list):
            for item in files[: self._settings.github_max_files_per_audit]:
                if not isinstance(item, Mapping):
                    continue
                filename = item.get("filename")
                if not isinstance(filename, str):
                    continue
                safe_files.append(
                    {
                        "filename": filename,
                        "status": item.get("status"),
                        "additions": item.get("additions"),
                        "deletions": item.get("deletions"),
                        "changes": item.get("changes"),
                    }
                )
        return {
            "status": payload.get("status"),
            "ahead_by": payload.get("ahead_by"),
            "behind_by": payload.get("behind_by"),
            "total_commits": payload.get("total_commits"),
            "files": safe_files,
        }

    def probe(
        self,
        repository_value: str,
    ) -> dict[str, object]:
        metadata = self.repository_metadata(repository_value)
        default_ref = (
            metadata.get("default_branch")
            if isinstance(metadata.get("default_branch"), str)
            else self._settings.github_default_ref
        )
        commit_sha, tree_sha = self.resolve_ref(
            repository_value,
            default_ref,
        )
        return {
            "repository": repository_value,
            "default_ref": default_ref,
            "commit_sha": commit_sha,
            "tree_sha": tree_sha,
            "metadata_read": True,
            "content_read": self._settings.github_allow_content_read,
            "read_only": True,
        }


def connector_status(settings: Settings) -> GitHubConnectorStatus:
    write_permissions = any(
        (
            settings.github_allow_write,
            settings.github_allow_branch_create,
            settings.github_allow_commit,
            settings.github_allow_pull_request,
            settings.github_allow_merge,
            settings.github_allow_workflow_dispatch,
        )
    )
    return GitHubConnectorStatus(
        enabled=settings.github_integration_enabled,
        configured=settings.github_configured,
        auth_mode=settings.github_auth_mode,
        read_only=settings.github_read_only,
        auto_audit_enabled=settings.github_orion_auto_audit_enabled,
        allowed_repositories=settings.github_allowed_repositories,
        allowed_roles=settings.github_allowed_roles,
        allowed_tenants_restricted=bool(
            settings.github_allowed_tenants
        ),
        allowed_users_restricted=bool(
            settings.github_allowed_users
        ),
        api_base_url=settings.github_api_base_url,
        api_version=settings.github_api_version,
        write_permissions=write_permissions,
    )
