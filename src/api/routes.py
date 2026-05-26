"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from src.agent.registry import DuplicateExternalIdError

router = APIRouter()
registry = AgentRegistry()


@router.get("/agents")
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(
    name: str,
    agent_type: str,
    config: Optional[Dict] = None,
    external_id: Optional[str] = None
):
    """Register a new agent, optionally with a unique external service account ID.

    external_id must be unique among active service accounts. Disabled accounts
    may reuse an external_id after a 30-day cooldown period.
    """
    try:
        agent_id = registry.register(name, agent_type, config, external_id=external_id)
        return {"agent_id": agent_id, "status": "registered"}
    except DuplicateExternalIdError as e:
        raise HTTPException(status_code=409, detail=str(e))


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


@router.get("/agents/external/{external_id}")
async def get_agent_by_external_id(external_id: str):
    """Look up an agent by its external service account identifier."""
    agent = registry.find_by_external_id(external_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent
