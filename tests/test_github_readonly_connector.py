import base64
import json

import httpx
import pytest

from orkio_platform.application.services import PlatformService
from orkio_platform.config import get_settings
from orkio_platform.domain.models import (
    AgentTurnContext,
    ChatRequest,
    PrincipalContext,
)
from orkio_platform.infrastructure.repositories import InMemoryRepository
from orkio_platform.integrations.github import (
    GitHubConnectorError,
    GitHubFileEvidence,
    GitHubReadOnlyClient,
)
from orkio_platform.integrations.repository_audit import (
    GitHubRepositoryAuditProvider,
    RepositoryAuditEvidence,
)
from orkio_platform.llm.contracts import LLMCompletionRequest, LLMResult
from orkio_platform.orchestration.capabilities import list_capabilities


def configure_token_connector(monkeypatch, *, auto_audit="true"):
    monkeypatch.setenv("PLATFORM_GITHUB_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_GITHUB_READ_ONLY", "true")
    monkeypatch.setenv("PLATFORM_GITHUB_AUTH_MODE", "token")
    monkeypatch.setenv("PLATFORM_GITHUB_TOKEN", "github-test-token")
    monkeypatch.setenv(
        "PLATFORM_GITHUB_ALLOWED_REPOSITORIES",
        "patroaiconsultech/repo-a",
    )
    monkeypatch.setenv(
        "PLATFORM_GITHUB_ORION_AUTO_AUDIT_ENABLED",
        auto_audit,
    )
    monkeypatch.setenv(
        "PLATFORM_GITHUB_ALLOWED_ROLES",
        "admin",
    )
    get_settings.cache_clear()
    return get_settings()


def test_github_config_fails_closed_on_any_write_flag(monkeypatch):
    configure_token_connector(monkeypatch)
    monkeypatch.setenv("PLATFORM_GITHUB_ALLOW_COMMIT", "true")
    get_settings.cache_clear()

    with pytest.raises(
        ValueError,
        match="PLATFORM_GITHUB_READONLY_VIOLATION",
    ):
        get_settings()


def test_github_auto_audit_requires_integration(monkeypatch):
    monkeypatch.setenv(
        "PLATFORM_GITHUB_ORION_AUTO_AUDIT_ENABLED",
        "true",
    )
    get_settings.cache_clear()

    with pytest.raises(
        ValueError,
        match=(
            "PLATFORM_GITHUB_ORION_AUTO_AUDIT_REQUIRES_INTEGRATION"
        ),
    ):
        get_settings()


def test_github_app_private_key_requires_valid_base64(monkeypatch):
    monkeypatch.setenv("PLATFORM_GITHUB_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_GITHUB_AUTH_MODE", "github_app")
    monkeypatch.setenv("PLATFORM_GITHUB_APP_ID", "123")
    monkeypatch.setenv(
        "PLATFORM_GITHUB_APP_INSTALLATION_ID",
        "456",
    )
    monkeypatch.setenv(
        "PLATFORM_GITHUB_APP_PRIVATE_KEY_B64",
        "not-base64",
    )
    monkeypatch.setenv(
        "PLATFORM_GITHUB_ALLOWED_REPOSITORIES",
        "patroaiconsultech/repo-a",
    )
    get_settings.cache_clear()

    with pytest.raises(
        ValueError,
        match="PLATFORM_GITHUB_APP_PRIVATE_KEY_B64_INVALID",
    ):
        get_settings()


def test_readonly_client_reads_allowlisted_repository(monkeypatch):
    settings = configure_token_connector(monkeypatch)
    observed = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        assert request.method == "GET"
        assert request.headers["authorization"] == (
            "Bearer github-test-token"
        )
        assert request.headers["x-github-api-version"] == "2026-03-10"
        path = request.url.path
        if path == "/repos/patroaiconsultech/repo-a":
            return httpx.Response(
                200,
                json={
                    "full_name": "patroaiconsultech/repo-a",
                    "private": True,
                    "default_branch": "main",
                    "archived": False,
                    "disabled": False,
                },
            )
        if path.endswith("/commits/main"):
            return httpx.Response(
                200,
                json={
                    "sha": "commit-1",
                    "commit": {"tree": {"sha": "tree-1"}},
                },
            )
        if path.endswith("/git/trees/tree-1"):
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {
                            "path": "src/app.py",
                            "type": "blob",
                            "sha": "blob-1",
                            "size": 30,
                        }
                    ],
                },
            )
        if path.endswith("/contents/src/app.py"):
            content = base64.b64encode(
                b'API_TOKEN="do-not-leak"\nprint("ok")\n'
            ).decode("ascii")
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "encoding": "base64",
                    "content": content,
                    "size": 37,
                    "sha": "blob-1",
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler)
    )
    github = GitHubReadOnlyClient(
        settings,
        client=http_client,
    )

    metadata = github.repository_metadata(
        "patroaiconsultech/repo-a"
    )
    assert metadata["default_branch"] == "main"
    commit_sha, tree_sha = github.resolve_ref(
        "patroaiconsultech/repo-a",
        "main",
    )
    assert (commit_sha, tree_sha) == ("commit-1", "tree-1")
    tree, truncated = github.tree(
        "patroaiconsultech/repo-a",
        tree_sha,
    )
    assert truncated is False
    evidence = github.file_content(
        "patroaiconsultech/repo-a",
        commit_sha=commit_sha,
        path=str(tree[0]["path"]),
        blob_sha=str(tree[0]["sha"]),
    )
    assert 'API_TOKEN="do-not-leak"' in evidence.content
    assert len(observed) == 4


def test_readonly_client_blocks_repository_outside_allowlist(
    monkeypatch,
):
    settings = configure_token_connector(monkeypatch)
    github = GitHubReadOnlyClient(settings)

    with pytest.raises(
        GitHubConnectorError,
        match="allowlist",
    ) as error:
        github.repository_metadata("another/repository")

    assert error.value.code == "GITHUB_REPOSITORY_NOT_ALLOWED"


class FakeAuditClient:
    def __init__(self):
        self.calls = 0

    def repository_metadata(self, repository):
        self.calls += 1
        return {
            "full_name": repository,
            "private": True,
            "default_branch": "main",
        }

    def resolve_ref(self, repository, ref):
        return "commit-sha", "tree-sha"

    def tree(self, repository, tree_sha):
        return (
            (
                {
                    "path": "src/config.py",
                    "sha": "blob-sha",
                    "size": 80,
                },
            ),
            False,
        )

    def path_is_readable(self, path):
        return True

    def file_content(
        self,
        repository,
        *,
        commit_sha,
        path,
        blob_sha=None,
    ):
        return GitHubFileEvidence(
            repository=repository,
            ref=commit_sha,
            commit_sha=commit_sha,
            path=path,
            blob_sha=blob_sha,
            content=(
                'PLATFORM_SECRET="secret-value"\n'
                "PLATFORM_REALTIME_VOICE_ENABLED = False\n"
            ),
            truncated=False,
        )

    def probe(self, repository):
        return {
            "repository": repository,
            "commit_sha": "commit-sha",
            "read_only": True,
        }


def audit_context(*, role="admin"):
    return AgentTurnContext(
        request_id="request-audit",
        execution_id="execution-audit",
        thread_id="thread-audit",
        tenant_id="tenant-a",
        user_id="admin-a",
        principal_role=role,
        requested_agent="Orion",
        resolved_agent="Orion",
        turn_owner="Orion",
        display_agent="Orion",
        route_family="explicit_agent",
    )


def test_audit_provider_collects_bounded_redacted_evidence(
    monkeypatch,
):
    settings = configure_token_connector(monkeypatch)
    fake = FakeAuditClient()
    provider = GitHubRepositoryAuditProvider(
        settings,
        client=fake,
    )

    evidence = provider.maybe_collect(
        audit_context(),
        "Execute uma auditoria interna do código.",
    )

    assert evidence is not None
    assert evidence.status == "success"
    assert evidence.files_read == 1
    assert "commit-sha" in evidence.prompt_block
    assert "src/config.py" in evidence.prompt_block
    assert "secret-value" not in evidence.prompt_block
    assert "<REDACTED>" in evidence.prompt_block
    assert "write_capabilities" in evidence.prompt_block


def test_audit_provider_denies_unauthorized_member_without_read(
    monkeypatch,
):
    settings = configure_token_connector(monkeypatch)
    fake = FakeAuditClient()
    provider = GitHubRepositoryAuditProvider(
        settings,
        client=fake,
    )

    evidence = provider.maybe_collect(
        audit_context(role="member"),
        "Auditoria war room do GitHub.",
    )

    assert evidence is not None
    assert evidence.status == "forbidden"
    assert evidence.code == "GITHUB_AUDIT_NOT_AUTHORIZED"
    assert fake.calls == 0


class CapturingProvider:
    provider_name = "capture"
    model_name = "capture-model"

    def __init__(self):
        self.requests = []

    def complete(self, request: LLMCompletionRequest):
        self.requests.append(request)
        return LLMResult(
            content="Auditoria concluída com evidências.",
            provider=self.provider_name,
            model=self.model_name,
        )


class StaticAuditProvider:
    def maybe_collect(self, context, objective):
        return RepositoryAuditEvidence(
            status="success",
            code="TEST",
            prompt_block="\nTOOL_EVIDENCE commit=abc path=src/app.py\n",
        )

    def status(self):
        return {"enabled": True}

    def probe(self):
        return {"status": "healthy"}


def test_orion_chat_receives_explicit_repository_tool_evidence():
    repository = InMemoryRepository()
    llm = CapturingProvider()
    service = PlatformService(
        repository,
        llm_provider=llm,
        repository_audit_provider=StaticAuditProvider(),
    )
    principal = PrincipalContext(
        tenant_id="tenant-a",
        user_id="admin-a",
        role="admin",
    )
    thread = service.create_thread(principal, "Audit")

    response = service.complete_chat(
        principal,
        ChatRequest(
            thread_id=thread.thread_id,
            content="Faça auditoria interna do código.",
            requested_agent="Orion",
            request_id="request-github-audit",
        ),
    )

    assert response.status == "success"
    assert "TOOL_EVIDENCE" in llm.requests[0].system_prompt
    assert llm.requests[0].agent_id == "Orion"


def test_capability_becomes_active_only_when_connector_is_ready(
    monkeypatch,
):
    configure_token_connector(monkeypatch)
    capabilities = {
        item.capability_id: item
        for item in list_capabilities()
    }

    github = capabilities["github_repository_readonly"]
    architecture = capabilities["architecture_indexer"]
    technical = capabilities["technical_architecture"]

    assert github.status == "active"
    assert github.availability == "available"
    assert architecture.status == "active"
    assert (
        "no repository tool connected"
        not in technical.limitations
    )


def test_github_api_base_url_is_restricted_to_official_api(
    monkeypatch,
):
    configure_token_connector(monkeypatch)
    monkeypatch.setenv(
        "PLATFORM_GITHUB_API_BASE_URL",
        "https://internal.example.test",
    )
    get_settings.cache_clear()

    with pytest.raises(
        ValueError,
        match="PLATFORM_GITHUB_API_BASE_URL_UNSUPPORTED",
    ):
        get_settings()


def test_github_installation_id_has_controlled_validation(
    monkeypatch,
):
    monkeypatch.setenv("PLATFORM_GITHUB_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_GITHUB_AUTH_MODE", "github_app")
    monkeypatch.setenv("PLATFORM_GITHUB_APP_ID", "123")
    monkeypatch.setenv(
        "PLATFORM_GITHUB_APP_INSTALLATION_ID",
        "not-an-integer",
    )
    monkeypatch.setenv(
        "PLATFORM_GITHUB_APP_PRIVATE_KEY_B64",
        base64.b64encode(
            b"-----BEGIN PRIVATE KEY-----\ninvalid\n"
            b"-----END PRIVATE KEY-----"
        ).decode("ascii"),
    )
    monkeypatch.setenv(
        "PLATFORM_GITHUB_ALLOWED_REPOSITORIES",
        "patroaiconsultech/repo-a",
    )
    get_settings.cache_clear()

    with pytest.raises(
        ValueError,
        match="PLATFORM_GITHUB_APP_INSTALLATION_ID_INVALID",
    ):
        get_settings()


def test_readonly_client_maps_forbidden_rate_limit(
    monkeypatch,
):
    settings = configure_token_connector(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0"},
            json={"message": "API rate limit exceeded"},
        )

    github = GitHubReadOnlyClient(
        settings,
        client=httpx.Client(
            transport=httpx.MockTransport(handler)
        ),
    )

    with pytest.raises(
        GitHubConnectorError,
        match="rate limit",
    ) as error:
        github.repository_metadata(
            "patroaiconsultech/repo-a"
        )

    assert error.value.code == "GITHUB_RATE_LIMITED"
    assert error.value.retryable is True


def test_github_app_token_is_scoped_to_allowlisted_repository_names(
    monkeypatch,
):
    private_key = (
        b"-----BEGIN PRIVATE KEY-----\n"
        b"not-used-by-this-test\n"
        b"-----END PRIVATE KEY-----"
    )
    monkeypatch.setenv("PLATFORM_GITHUB_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("PLATFORM_GITHUB_READ_ONLY", "true")
    monkeypatch.setenv("PLATFORM_GITHUB_AUTH_MODE", "github_app")
    monkeypatch.setenv("PLATFORM_GITHUB_APP_ID", "123")
    monkeypatch.setenv(
        "PLATFORM_GITHUB_APP_INSTALLATION_ID",
        "456",
    )
    monkeypatch.setenv(
        "PLATFORM_GITHUB_APP_PRIVATE_KEY_B64",
        base64.b64encode(private_key).decode("ascii"),
    )
    monkeypatch.setenv(
        "PLATFORM_GITHUB_ALLOWED_REPOSITORIES",
        (
            "patroaiconsultech/repo-a,"
            "patroaiconsultech/repo-b"
        ),
    )
    get_settings.cache_clear()
    settings = get_settings()
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["json"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "token": "installation-token",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )

    from orkio_platform.integrations.github import (
        GitHubCredentialProvider,
    )

    credentials = GitHubCredentialProvider(
        settings,
        client=httpx.Client(
            transport=httpx.MockTransport(handler)
        ),
        now=lambda: 1_700_000_000,
    )
    credentials._app_jwt = lambda: "signed-app-jwt"  # type: ignore[method-assign]

    assert credentials.token() == "installation-token"
    assert observed["json"]["repositories"] == [
        "repo-a",
        "repo-b",
    ]
    assert observed["json"]["permissions"] == {
        "contents": "read",
        "metadata": "read",
    }
