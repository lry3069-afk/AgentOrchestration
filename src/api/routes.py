"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Dict, Optional, List

from src.agent import AgentRegistry, AgentStatus
from src.common.csrf import csrf_manager
from src.common.embedded_sessions import create_embedded_session, configure_embedded_sessions
from src.common.service_accounts import service_account_registry, ServiceAccountStatus

router = APIRouter()
registry = AgentRegistry()


@router.get("/agents")
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(name: str, agent_type: str, config: Optional[Dict] = None):
    agent_id = registry.register(name, agent_type, config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if not registry.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.PAUSED):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "stopped"}


@router.get("/agents/count")
async def agent_count():
    return {"count": registry.count()}


@router.post("/org/switch")
async def switch_organization(
    target_org_id: str,
    x_csrf_token: str = Header(..., alias="X-CSRF-Token"),
    authorization: str = Header(..., alias="Authorization"),
):
    """Switch active organization context.

    Requires a CSRF token bound to the session and target organization.
    The token is single-use and expires after 5 minutes.
    """
    # Extract session identifier from Bearer token
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    session_id = authorization[7:]  # Strip "Bearer " prefix

    # Validate CSRF token
    is_valid, error = csrf_manager.validate(x_csrf_token, session_id, target_org_id)
    if not is_valid:
        raise HTTPException(status_code=403, detail=error)

    return {
        "status": "switched",
        "active_organization": target_org_id,
    }


@router.get("/org/csrf-token")
async def get_csrf_token(
    target_org_id: str,
    authorization: str = Header(..., alias="Authorization"),
):
    """Obtain a CSRF token for organization switch.

    Returns a single-use token bound to the current session and target organization.
    Token expires after 5 minutes.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    session_id = authorization[7:]

    token = csrf_manager.generate(session_id, target_org_id)
    return {"csrf_token": token, "expires_in": 300}


@router.post("/embedded/console/session")
async def create_embedded_console_session(
    authorization: str = Header(..., alias="Authorization"),
    workspace_id: Optional[str] = None,
    tenant: Optional[str] = None,
):
    """Create an embedded admin console session.

    Validates JWT token with strict audience, issuer, tenant, and expiration checks.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization[7:]  # Strip "Bearer " prefix

    try:
        session = create_embedded_session(token)
        return {
            "session_id": session["session_id"],
            "workspace_id": session["workspace_id"],
            "tenant": session["tenant"],
            "expires_at": session["expires_at"],
        }
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/admin/embedded/config")
async def configure_embedded_session_validation(
    audience: str,
    issuer: str,
    tenants: Optional[str] = None,
    secret: Optional[str] = None,
    max_ttl: Optional[int] = None,
    admin_token: str = Header(..., alias="X-Admin-Token"),
):
    """Configure embedded session validation (admin only)."""
    if admin_token != "admin-secret-token":
        raise HTTPException(status_code=403, detail="Admin token required")

    tenant_set = set(tenants.split(",")) if tenants else set()
    configure_embedded_sessions(
        audience=audience,
        issuer=issuer,
        tenants=tenant_set,
        secret=secret,
        max_ttl=max_ttl,
    )

    return {"status": "configured"}


# === Service Account Endpoints ===

@router.post("/service-accounts")
async def create_service_account(
    name: str,
    external_id: str,
    organization_id: str,
    metadata: Optional[Dict] = None,
):
    """Create a service account with unique external ID validation."""
    try:
        account = service_account_registry.create(name, external_id, organization_id, metadata)
        return {
            "account_id": account.account_id,
            "name": account.name,
            "external_id": account.external_id,
            "organization_id": account.organization_id,
            "status": account.status.value,
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/service-accounts/{account_id}")
async def get_service_account(account_id: str):
    account = service_account_registry.get(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Service account not found")
    return {
        "account_id": account.account_id,
        "name": account.name,
        "external_id": account.external_id,
        "organization_id": account.organization_id,
        "status": account.status.value,
        "metadata": account.metadata,
    }


@router.put("/service-accounts/{account_id}")
async def update_service_account(
    account_id: str,
    name: Optional[str] = None,
    external_id: Optional[str] = None,
    metadata: Optional[Dict] = None,
):
    """Update a service account. External ID changes are validated for uniqueness."""
    try:
        account = service_account_registry.update(account_id, name, external_id, metadata)
        return {
            "account_id": account.account_id,
            "name": account.name,
            "external_id": account.external_id,
            "organization_id": account.organization_id,
            "status": account.status.value,
        }
    except ValueError as e:
        raise HTTPException(status_code=409 if "already in use" in str(e) else 400, detail=str(e))


@router.post("/service-accounts/{account_id}/disable")
async def disable_service_account(account_id: str):
    """Disable a service account. Its external ID becomes available for reuse."""
    try:
        account = service_account_registry.disable(account_id)
        return {"account_id": account.account_id, "status": account.status.value}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/service-accounts/{account_id}/restore")
async def restore_service_account(account_id: str):
    """Restore a disabled service account. External ID must be unique among active accounts."""
    try:
        account = service_account_registry.restore(account_id)
        return {"account_id": account.account_id, "status": account.status.value}
    except ValueError as e:
        raise HTTPException(status_code=409 if "already in use" in str(e) else 404, detail=str(e))


@router.get("/organizations/{org_id}/service-accounts")
async def list_service_accounts(org_id: str, status: Optional[str] = None):
    status_filter = ServiceAccountStatus(status) if status else None
    accounts = service_account_registry.list_by_org(org_id, status_filter)
    return {
        "accounts": [
            {
                "account_id": a.account_id,
                "name": a.name,
                "external_id": a.external_id,
                "status": a.status.value,
            }
            for a in accounts
        ]
    }


@router.get("/organizations/{org_id}/service-accounts/duplicates")
async def find_duplicate_external_ids(org_id: str):
    """Find existing duplicate external IDs for migration purposes."""
    duplicates = service_account_registry.get_existing_duplicates(org_id)
    return {"organization_id": org_id, "duplicates": duplicates}
