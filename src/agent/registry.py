"""Agent Registry — Manages agent lifecycle and metadata."""

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class DuplicateExternalIdError(ValueError):
    """Raised when an external_id is already in use by an active agent."""
    pass


class AgentRegistry:
    # Terminal states — agents in these states can be restored / reused
    _TERMINAL_STATUSES = {AgentStatus.STOPPED.value, AgentStatus.FAILED.value, AgentStatus.TERMINATED.value}
    # Active statuses — block external_id reuse
    _ACTIVE_STATUSES = {AgentStatus.PENDING.value, AgentStatus.RUNNING.value, AgentStatus.PAUSED.value}

    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        # external_id → agent_id (only active agents are indexed)
        self._external_id_index: Dict[str, str] = {}

    def _is_active(self, status: str) -> bool:
        return status in self._ACTIVE_STATUSES

    def _register_external_id(self, external_id: str, agent_id: str) -> None:
        """Add external_id → agent_id mapping. Raises DuplicateExternalIdError if already taken by an active agent."""
        existing = self._external_id_index.get(external_id)
        if existing is not None:
            existing_agent = self._agents.get(existing)
            if existing_agent is None or self._is_active(existing_agent["status"]):
                raise DuplicateExternalIdError(
                    f"External ID '{external_id}' is already assigned to active agent '{existing}'"
                )
        self._external_id_index[external_id] = agent_id

    def _release_external_id(self, agent_id: str) -> None:
        """Remove external_id mapping when an agent is deleted or disabled."""
        to_remove = [eid for eid, aid in self._external_id_index.items() if aid == agent_id]
        for eid in to_remove:
            del self._external_id_index[eid]

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
        external_id: Optional[str] = None,
    ) -> str:
        if external_id is not None:
            self._register_external_id(external_id, "<pending>")  # reserve slot

        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "external_id": external_id,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }

        if external_id is not None:
            self._external_id_index[external_id] = agent_id

        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        old_status = self._agents[agent_id]["status"]
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        # If transitioning from active to terminal, release external_id slot
        if self._is_active(old_status) and status.value in self._TERMINAL_STATUSES:
            self._release_external_id(agent_id)
        return True

    def update_external_id(self, agent_id: str, external_id: Optional[str]) -> bool:
        """Update the external_id of an agent. Returns False if agent not found."""
        if agent_id not in self._agents:
            return False
        agent = self._agents[agent_id]
        old_external_id = agent.get("external_id")

        if old_external_id is not None:
            self._release_external_id(agent_id)

        if external_id is not None:
            self._register_external_id(external_id, agent_id)
            self._external_id_index[external_id] = agent_id

        agent["external_id"] = external_id
        agent["updated_at"] = time.time()
        return True

    def restore(self, agent_id: str) -> bool:
        """Restore a TERMINATED/STOPPED/FAILED agent back to PENDING."""
        if agent_id not in self._agents:
            return False
        agent = self._agents[agent_id]
        if agent["status"] not in self._TERMINAL_STATUSES:
            return False
        external_id = agent.get("external_id")
        if external_id is not None:
            # Re-register external_id for the restored agent
            self._register_external_id(external_id, agent_id)
            self._external_id_index[external_id] = agent_id
        agent["status"] = AgentStatus.PENDING.value
        agent["updated_at"] = time.time()
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._release_external_id(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def get_by_external_id(self, external_id: str) -> Optional[Dict[str, Any]]:
        agent_id = self._external_id_index.get(external_id)
        if agent_id is None:
            return None
        return self._agents.get(agent_id)
