"""Regression tests for collaboration auth — Issue #4687.

Coverage:
- Anonymous requests are denied (401).
- Stale credentials are denied (401).
- Revoked credentials are denied (403).
- Insufficient role for saved-view sharing is denied (403).
- Cross-workspace access is denied (403).
- Authorized users with correct workspace + role succeed.
"""

import time

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.common.auth import (
    CollaborationAuthService,
    Principal,
    StaleCredentialError,
    RevokedCredentialError,
    InsufficientMembershipError,
    AnonymousAccessError,
)


# ---------------------------------------------------------------------------
# Helper: build a valid Bearer token
# ---------------------------------------------------------------------------

def _token(workspace: str, role: str, offset_seconds: int = 3600) -> str:
    """Return a Bearer token that encodes workspace / role / expiry."""
    exp = str(int(time.time() + offset_seconds))
    return f"workspace:{workspace}:role:{role}:exp:{exp}"


def _headers(workspace: str = "ws-shared", role: str = "owner") -> dict:
    return {"Authorization": f"Bearer {_token(workspace, role)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def auth_service():
    """Fresh CollaborationAuthService for unit-level tests."""
    return CollaborationAuthService()


# ---------------------------------------------------------------------------
# Unit tests: CollaborationAuthService.enforce_membership
# ---------------------------------------------------------------------------

class TestEnforceMembershipUnit:
    def test_none_principal_raises(self, auth_service):
        with pytest.raises(AnonymousAccessError, match="No credential"):
            auth_service.enforce_membership(None)

    def test_stale_credential_raises(self, auth_service):
        p = Principal(
            user_id="u1", workspace_id="ws1", role="owner",
            session_id="s1", expires_at=time.time() - 10,
        )
        with pytest.raises(StaleCredentialError, match="expired"):
            auth_service.enforce_membership(p)

    def test_revoked_session_raises(self, auth_service):
        auth_service.revoke_session("s-revoked")
        p = Principal(
            user_id="u1", workspace_id="ws1", role="owner",
            session_id="s-revoked",
            expires_at=time.time() + 3600,
        )
        with pytest.raises(RevokedCredentialError, match="revoked"):
            auth_service.enforce_membership(p)

    def test_no_workspace_raises(self, auth_service):
        p = Principal(
            user_id="u1", workspace_id="", role="owner",
            session_id="s1", expires_at=time.time() + 3600,
        )
        with pytest.raises(InsufficientMembershipError, match="not scoped"):
            auth_service.enforce_membership(p)

    def test_viewer_cannot_share(self, auth_service):
        p = Principal(
            user_id="u1", workspace_id="ws1", role="viewer",
            session_id="s1", expires_at=time.time() + 3600,
        )
        with pytest.raises(InsufficientMembershipError, match="insufficient"):
            auth_service.enforce_membership(p, min_role="editor")

    def test_editor_can_share(self, auth_service):
        p = Principal(
            user_id="u1", workspace_id="ws1", role="editor",
            session_id="s1", expires_at=time.time() + 3600,
        )
        result = auth_service.enforce_membership(p, min_role="editor")
        assert result.role == "editor"

    def test_owner_passes_all_checks(self, auth_service):
        p = Principal(
            user_id="u1", workspace_id="ws1", role="owner",
            session_id="s1", expires_at=time.time() + 3600,
        )
        assert auth_service.enforce_membership(p) is p
        assert auth_service.enforce_membership(p, min_role="editor") is p
        assert auth_service.enforce_membership(p, min_role="owner") is p

    def test_can_share_saved_view(self, auth_service):
        owner = Principal("u1", "ws1", "owner", "s1", time.time() + 3600)
        editor = Principal("u2", "ws1", "editor", "s2", time.time() + 3600)
        viewer = Principal("u3", "ws1", "viewer", "s3", time.time() + 3600)
        assert auth_service.can_share_saved_view(owner) is True
        assert auth_service.can_share_saved_view(editor) is True
        assert auth_service.can_share_saved_view(viewer) is False

    def test_revocation_is_persistent(self, auth_service):
        p = Principal("u1", "ws1", "owner", "s-kill", time.time() + 3600)
        auth_service.revoke_session("s-kill")
        assert auth_service.is_revoked(p) is True
        with pytest.raises(RevokedCredentialError):
            auth_service.enforce_membership(p)


# ---------------------------------------------------------------------------
# Integration tests: full API with FastAPI TestClient
# ---------------------------------------------------------------------------

class TestAnonymousDenied:
    """Anonymous requests must receive 401."""

    def test_list_views_anonymous(self, client):
        resp = client.get("/api/v2/views")
        assert resp.status_code == 401

    def test_create_view_anonymous(self, client):
        resp = client.post("/api/v2/views", json={"name": "v", "query": {}})
        assert resp.status_code == 401

    def test_share_view_anonymous(self, client):
        resp = client.post("/api/v2/views/v1/share", json={"target_workspace": "ws2"})
        assert resp.status_code == 401

    def test_get_view_anonymous(self, client):
        resp = client.get("/api/v2/views/v1")
        assert resp.status_code == 401


class TestStaleCredentialsDenied:
    """Expired credentials must receive 401."""

    def test_stale_token_blocked(self, client):
        h = {"Authorization": f"Bearer {_token('ws1', 'owner', offset_seconds=-1)}"}
        resp = client.get("/api/v2/views", headers=h)
        assert resp.status_code == 401
        assert "expired" in resp.json()["error"].lower()


class TestRevokedCredentialsDenied:
    """Revoked credentials must receive 403."""

    def test_revoked_session_blocked(self, client):
        from src.api.middleware import _auth_service
        _auth_service.revoke_session("s-ws1-viewer")
        h = _headers("ws1", "viewer")
        resp = client.get("/api/v2/views", headers=h)
        assert resp.status_code == 403
        # Cleanup
        _auth_service._revoked_sessions.discard("s-ws1-viewer")


class TestInsufficientRoleDenied:
    """Viewers cannot share; editors and owners can."""

    def test_viewer_share_denied(self, client):
        # First create a view as owner.
        resp = client.post("/api/v2/views", json={"name": "v", "query": {}},
                          headers=_headers("ws1", "owner"))
        assert resp.status_code == 200
        view_id = resp.json()["view_id"]

        # Viewer tries to share → 403.
        resp = client.post(f"/api/v2/views/{view_id}/share",
                          json={"target_workspace": "ws2"},
                          headers=_headers("ws1", "viewer"))
        assert resp.status_code == 403

    def test_editor_can_share(self, client):
        resp = client.post("/api/v2/views", json={"name": "v", "query": {}},
                          headers=_headers("ws1", "owner"))
        view_id = resp.json()["view_id"]

        resp = client.post(f"/api/v2/views/{view_id}/share",
                          json={"target_workspace": "ws2"},
                          headers=_headers("ws1", "editor"))
        assert resp.status_code == 200
        assert "ws2" in resp.json()["shared_with"]


class TestCrossWorkspaceDenied:
    """Callers cannot access views from workspaces they don't belong to."""

    def test_cannot_access_unshared_view(self, client):
        resp = client.post("/api/v2/views", json={"name": "v", "query": {}},
                          headers=_headers("ws-private", "owner"))
        view_id = resp.json()["view_id"]

        # Another workspace tries to fetch → 403.
        resp = client.get(f"/api/v2/views/{view_id}", headers=_headers("ws-other", "owner"))
        assert resp.status_code == 403

    def test_cannot_share_other_workspace_view(self, client):
        resp = client.post("/api/v2/views", json={"name": "v", "query": {}},
                          headers=_headers("ws-a", "owner"))
        view_id = resp.json()["view_id"]

        # ws-b owner tries to share ws-a's view → 403.
        resp = client.post(f"/api/v2/views/{view_id}/share",
                          json={"target_workspace": "ws-c"},
                          headers=_headers("ws-b", "owner"))
        assert resp.status_code == 403


class TestAuthorizedWorkflowSucceeds:
    """Normal collaboration flow: create, share, access."""

    def test_full_flow(self, client):
        # 1. Owner creates view in ws-lead.
        resp = client.post("/api/v2/views",
                          json={"name": "Q3 pipeline", "query": {"status": "active"}},
                          headers=_headers("ws-lead", "owner"))
        assert resp.status_code == 200
        view_id = resp.json()["view_id"]

        # 2. Owner shares with ws-support.
        resp = client.post(f"/api/v2/views/{view_id}/share",
                          json={"target_workspace": "ws-support"},
                          headers=_headers("ws-lead", "owner"))
        assert resp.status_code == 200
        assert "ws-support" in resp.json()["shared_with"]

        # 3. ws-support member fetches the shared view.
        resp = client.get(f"/api/v2/views/{view_id}", headers=_headers("ws-support", "viewer"))
        assert resp.status_code == 200
        assert resp.json()["name"] == "Q3 pipeline"

        # 4. ws-support member lists all shared views.
        resp = client.get("/api/v2/views", headers=_headers("ws-support", "viewer"))
        assert resp.status_code == 200
        views = resp.json()["views"]
        assert any(v["id"] == view_id for v in views)

        # 5. Unrelated workspace still cannot access.
        resp = client.get(f"/api/v2/views/{view_id}", headers=_headers("ws-intruder", "owner"))
        assert resp.status_code == 403

    def test_owner_still_works_after_sharing(self, client):
        resp = client.post("/api/v2/views",
                          json={"name": "v", "query": {}},
                          headers=_headers("ws-main", "owner"))
        view_id = resp.json()["view_id"]

        # Share
        client.post(f"/api/v2/views/{view_id}/share",
                   json={"target_workspace": "ws-peer"},
                   headers=_headers("ws-main", "owner"))

        # Owner can still access
        resp = client.get(f"/api/v2/views/{view_id}", headers=_headers("ws-main", "owner"))
        assert resp.status_code == 200

    def test_empty_workspace_member_sees_no_views(self, client):
        resp = client.get("/api/v2/views", headers=_headers("ws-empty", "owner"))
        assert resp.status_code == 200
        assert resp.json()["views"] == []