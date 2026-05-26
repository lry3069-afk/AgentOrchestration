"""API route definitions."""

from fastapi import APIRouter, HTTPException, Query
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
    external_id: Optional[str] = Query(None, description="External identity provider ID"),
):
    try:
        agent_id = registry.register(name, agent_type, config, external_id=external_id)
        return {"agent_id": agent_id, "status": "registered", "external_id": external_id}
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


@router.post("/agents/{agent_id}/restore")
async def restore_agent(agent_id: str):
    """Restore a TERMINATED/STOPPED/FAILED agent to PENDING status."""
    if not registry.restore(agent_id):
        agent = registry.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{agent_id}' cannot be restored — current status is '{agent['status']}'"
        )
    return {"status": "restored", "agent_id": agent_id}


@router.patch("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    external_id: Optional[str] = Query(None, description="New external ID"),
):
    """Update agent metadata (currently: external_id)."""
    try:
        success = registry.update_external_id(agent_id, external_id)
        if not success:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"status": "updated", "agent_id": agent_id, "external_id": external_id}
    except DuplicateExternalIdError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/agents/by-external-id/{external_id}")
async def get_agent_by_external_id(external_id: str):
    """Look up an agent by its external identity provider ID."""
    agent = registry.get_by_external_id(external_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"No active agent found for external_id '{external_id}'")
    return agent


@router.get("/agents/count")
async def agent_count():
    return {"count": registry.count()}
