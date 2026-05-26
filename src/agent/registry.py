"""Agent Registry — Manages agent lifecycle and metadata."""

import json
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


class DuplicateExternalIdError(Exception):
    """Raised when a service account external ID is already in use."""
    pass


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._external_ids: Dict[str, str] = {}  # external_id -> agent_id mapping

    def _check_external_id_unique(self, external_id: str, organization: Optional[str] = None) -> None:
        """Validate that an external ID is unique among active service accounts.

        Disabled (TERMINATED/STOPPED) accounts may reuse external IDs after
        a 30-day cooldown period since their last update.
        """
        if external_id in self._external_ids:
            existing_agent_id = self._external_ids[external_id]
            existing = self._agents.get(existing_agent_id)
            if existing:
                status = existing.get("status", "")
                if status not in (AgentStatus.TERMINATED.value, AgentStatus.STOPPED.value):
                    raise DuplicateExternalIdError(
                        f"External ID {external_id!r} is already in use "
                        f"by an active service account ({existing_agent_id})"
                    )
                # Allow reuse if disabled for more than 30 days
                updated_at = existing.get("updated_at", 0)
                if time.time() - updated_at < 30 * 86400:
                    raise DuplicateExternalIdError(
                        f"External ID {external_id!r} was recently used. "
                        f"Must wait 30 days after deactivation before reuse."
                    )
                # Clean up old mapping
                del self._external_ids[external_id]

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
        external_id: Optional[str] = None
    ) -> str:
        if external_id:
            self._check_external_id_unique(external_id)

        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "external_id": external_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }

        if external_id:
            self._external_ids[external_id] = agent_id

        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(self, status: Optional[AgentStatus] = None, group: Optional[str] = None) -> List[Dict[str, Any]]:
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
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        # Clean up external ID mapping
        if agent.get("external_id"):
            self._external_ids.pop(agent["external_id"], None)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def find_by_external_id(self, external_id: str) -> Optional[Dict[str, Any]]:
        """Look up an agent by its external service account ID."""
        agent_id = self._external_ids.get(external_id)
        if agent_id:
            return self._agents.get(agent_id)
        return None
