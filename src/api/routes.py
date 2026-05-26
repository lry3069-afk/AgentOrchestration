"""API route definitions."""

import hashlib
import hmac
import os
import secrets
import time
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus

router = APIRouter()
registry = AgentRegistry()

# CSRF token store: maps session_id -> {org_id: token}
_csrf_tokens: Dict[str, Dict[str, str]] = {}
CSRF_TOKEN_TTL = 3600  # 1 hour


def _generate_csrf_token(session_id: str, org_id: str) -> str:
    """Generate a CSRF token bound to session and target organization."""
    secret = os.environ.get("CSRF_SECRET", secrets.token_hex(32))
    timestamp = str(int(time.time()))
    payload = f"{session_id}:{org_id}:{timestamp}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    token = f"{timestamp}.{signature}"
    if session_id not in _csrf_tokens:
        _csrf_tokens[session_id] = {}
    _csrf_tokens[session_id][org_id] = token
    return token


def _verify_csrf_token(session_id: str, org_id: str, token: str) -> bool:
    """Verify CSRF token is bound to session and target organization."""
    secret = os.environ.get("CSRF_SECRET", secrets.token_hex(32))
    try:
        timestamp_str, signature = token.split(".", 1)
        timestamp = int(timestamp_str)
        if time.time() - timestamp > CSRF_TOKEN_TTL:
            return False
        payload = f"{session_id}:{org_id}:{timestamp_str}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return False
        # Token cannot be reused for a different organization
        stored = _csrf_tokens.get(session_id, {}).get(org_id)
        if stored != token:
            return False
        return True
    except (ValueError, IndexError):
        return False


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


@router.get("/organizations/csrf-token")
async def get_csrf_token(
    session_id: str = Header(..., alias="X-Session-Id"),
    org_id: str = Header(..., alias="X-Target-Org"),
):
    """Issue a CSRF token bound to session and target organization."""
    token = _generate_csrf_token(session_id, org_id)
    return {"csrf_token": token, "org_id": org_id}


@router.post("/organizations/switch")
async def switch_organization(
    org_id: str,
    csrf_token: str = Header(..., alias="X-CSRF-Token"),
    session_id: str = Header(..., alias="X-Session-Id"),
):
    """Switch active organization. Requires CSRF token bound to session + org."""
    if not _verify_csrf_token(session_id, org_id, csrf_token):
        raise HTTPException(status_code=403, detail="Invalid or mismatched CSRF token")
    # Invalidate used token
    if session_id in _csrf_tokens:
        _csrf_tokens[session_id].pop(org_id, None)
    return {"status": "switched", "org_id": org_id}