"""Tests for JWT audience validation in embedded console sessions."""

import pytest
import time
import jwt
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.common.embedded_sessions import JWTSessionValidator, EmbeddedSessionConfig


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def valid_jwt_token():
    """Generate a valid JWT token for testing."""
    payload = {
        "sub": "workspace-123",
        "aud": "agent-orchestrator-embedded",
        "iss": "agent-orchestrator",
        "tenant": "acme-corp",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "jti": "test-jti-123",
    }
    return jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")


@pytest.fixture
def validator():
    config = EmbeddedSessionConfig(
        expected_audience="agent-orchestrator-embedded",
        expected_issuer="agent-orchestrator",
        allowed_tenants={"acme-corp", "other-corp"},
        max_session_ttl=3600,
    )
    return JWTSessionValidator(config, "agent-orchestrator-embedded-secret-key")


class TestJWTSessionValidator:
    def test_valid_token(self, validator):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "agent-orchestrator",
            "tenant": "acme-corp",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, claims = validator.validate(token)
        assert is_valid
        assert error == ""
        assert claims["sub"] == "workspace-123"

    def test_wrong_audience(self, validator):
        payload = {
            "sub": "workspace-123",
            "aud": "wrong-audience",
            "iss": "agent-orchestrator",
            "tenant": "acme-corp",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, _ = validator.validate(token)
        assert not is_valid
        assert "audience" in error.lower()

    def test_missing_audience(self, validator):
        payload = {
            "sub": "workspace-123",
            "iss": "agent-orchestrator",
            "tenant": "acme-corp",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, _ = validator.validate(token)
        assert not is_valid
        assert "audience" in error.lower()

    def test_wrong_issuer(self, validator):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "wrong-issuer",
            "tenant": "acme-corp",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, _ = validator.validate(token)
        assert not is_valid
        assert "issuer" in error.lower()

    def test_missing_issuer(self, validator):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "tenant": "acme-corp",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, _ = validator.validate(token)
        assert not is_valid
        assert "issuer" in error.lower()

    def test_tenant_not_allowed(self, validator):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "agent-orchestrator",
            "tenant": "unauthorized-tenant",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, _ = validator.validate(token)
        assert not is_valid
        assert "tenant not allowed" in error.lower()

    def test_missing_tenant(self, validator):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "agent-orchestrator",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, _ = validator.validate(token)
        assert not is_valid
        assert "tenant" in error.lower()

    def test_expired_token(self, validator):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "agent-orchestrator",
            "tenant": "acme-corp",
            "exp": int(time.time()) - 3600,
            "iat": int(time.time()) - 7200,
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, _ = validator.validate(token)
        assert not is_valid
        assert "expired" in error.lower()

    def test_missing_expiration(self, validator):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "agent-orchestrator",
            "tenant": "acme-corp",
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, _ = validator.validate(token)
        assert not is_valid
        assert "expiration" in error.lower()

    def test_ttl_exceeds_maximum(self, validator):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "agent-orchestrator",
            "tenant": "acme-corp",
            "exp": int(time.time()) + 7200,  # 2 hours > 1 hour max
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        is_valid, error, _ = validator.validate(token)
        assert not is_valid
        assert "exceeds maximum" in error.lower()

    def test_invalid_token_format(self, validator):
        is_valid, error, _ = validator.validate("not.a.jwt.token")
        assert not is_valid
        assert "invalid" in error.lower()

    def test_empty_token(self, validator):
        is_valid, error, _ = validator.validate("")
        assert not is_valid
        assert "missing" in error.lower()


class TestEmbeddedConsoleSessionAPI:
    def test_create_session_with_valid_token(self, client, valid_jwt_token):
        response = client.post(
            "/api/v2/embedded/console/session",
            headers={"Authorization": f"Bearer {valid_jwt_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["workspace_id"] == "workspace-123"
        assert data["tenant"] == "acme-corp"

    def test_create_session_without_auth(self, client):
        response = client.post("/api/v2/embedded/console/session")
        assert response.status_code == 401

    def test_create_session_with_wrong_audience(self, client):
        payload = {
            "sub": "workspace-123",
            "aud": "wrong-audience",
            "iss": "agent-orchestrator",
            "tenant": "acme-corp",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        response = client.post(
            "/api/v2/embedded/console/session",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert "audience" in response.json()["detail"].lower()

    def test_create_session_with_expired_token(self, client):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "agent-orchestrator",
            "tenant": "acme-corp",
            "exp": int(time.time()) - 3600,
            "iat": int(time.time()) - 7200,
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        response = client.post(
            "/api/v2/embedded/console/session",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert "expired" in response.json()["detail"].lower()

    def test_create_session_with_wrong_issuer(self, client):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "wrong-issuer",
            "tenant": "acme-corp",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        response = client.post(
            "/api/v2/embedded/console/session",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert "issuer" in response.json()["detail"].lower()

    def test_create_session_with_unauthorized_tenant(self, client):
        payload = {
            "sub": "workspace-123",
            "aud": "agent-orchestrator-embedded",
            "iss": "agent-orchestrator",
            "tenant": "unauthorized-tenant",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        token = jwt.encode(payload, "agent-orchestrator-embedded-secret-key", algorithm="HS256")
        response = client.post(
            "/api/v2/embedded/console/session",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert "tenant not allowed" in response.json()["detail"].lower()

    def test_configure_embedded_sessions_admin(self, client):
        response = client.post(
            "/api/v2/admin/embedded/config",
            params={
                "audience": "new-audience",
                "issuer": "new-issuer",
                "tenants": "tenant-a,tenant-b",
                "max_ttl": 7200,
            },
            headers={"X-Admin-Token": "admin-secret-token"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "configured"

    def test_configure_embedded_sessions_unauthorized(self, client):
        response = client.post(
            "/api/v2/admin/embedded/config",
            params={
                "audience": "new-audience",
                "issuer": "new-issuer",
            },
            headers={"X-Admin-Token": "wrong-token"}
        )
        assert response.status_code == 403
