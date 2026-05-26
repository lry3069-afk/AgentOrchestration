"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus

router = APIRouter()
registry = AgentRegistry()


@router.get("/agents")
async def list_agents(
    status: Optional[str] = None, group: Optional[str] = None
):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(
    name: str,
    agent_type: str,
    config: Optional[Dict] = None,
    external_id: Optional[str] = None,
    organization_id: Optional[str] = None,
):
    try:
        agent_id = registry.register(
            name=name,
            agent_type=agent_type,
            config=config,
            external_id=external_id,
            organization_id=organization_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
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


@router.get("/agents/external/{external_id}")
async def get_agent_by_external_id(
    external_id: str, organization_id: Optional[str] = None
):
    agent = registry.get_by_external_id(external_id, organization_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/service-accounts")
async def provision_service_account(
    name: str,
    external_id: str,
    organization_id: str,
    agent_type: str = "service-account",
    config: Optional[Dict] = None,
):
    try:
        agent_id = registry.register(
            name=name,
            agent_type=agent_type,
            config=config,
            external_id=external_id,
            organization_id=organization_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "agent_id": agent_id,
        "external_id": external_id,
        "organization_id": organization_id,
        "status": "provisioned",
    }