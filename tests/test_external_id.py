"""Tests for external ID uniqueness — Issue #4844."""

import pytest
from src.agent.registry import AgentRegistry, AgentStatus, DuplicateExternalIdError


class TestExternalIdUniqueness:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_register_with_external_id(self):
        """Agent can be registered with an external_id."""
        agent_id = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        agent = self.registry.get(agent_id)
        assert agent["external_id"] == "ext-001"

    def test_register_two_agents_same_external_id_active_rejected(self):
        """Second active agent with the same external_id is rejected."""
        self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        with pytest.raises(DuplicateExternalIdError):
            self.registry.register("svc-b", "worker.processor", external_id="ext-001")

    def test_register_same_external_id_after_stopped_allowed(self):
        """External ID can be reused once the first agent is in a terminal state."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        self.registry.update_status(id1, AgentStatus.STOPPED)
        id2 = self.registry.register("svc-b", "worker.processor", external_id="ext-001")
        assert id2 != id1
        assert self.registry.get(id2)["external_id"] == "ext-001"

    def test_register_same_external_id_after_failed_allowed(self):
        """External ID can be reused after FAILED state."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        self.registry.update_status(id1, AgentStatus.FAILED)
        id2 = self.registry.register("svc-b", "worker.processor", external_id="ext-001")
        assert id2 != id1

    def test_register_same_external_id_after_terminated_allowed(self):
        """External ID can be reused after TERMINATED state."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        self.registry.update_status(id1, AgentStatus.TERMINATED)
        id2 = self.registry.register("svc-b", "worker.processor", external_id="ext-001")
        assert id2 != id1

    def test_update_external_id_to_duplicate_blocked(self):
        """An active agent cannot adopt an external_id already in use."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        id2 = self.registry.register("svc-b", "worker.processor")  # no external_id
        with pytest.raises(DuplicateExternalIdError):
            self.registry.update_external_id(id2, "ext-001")

    def test_update_external_id_same_owner_allowed(self):
        """An agent can keep its own external_id during update."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        result = self.registry.update_external_id(id1, "ext-001")
        assert result is True
        assert self.registry.get(id1)["external_id"] == "ext-001"

    def test_update_external_id_clears_old_slot(self):
        """Updating from one external_id to another releases the old slot."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        id2 = self.registry.register("svc-b", "worker.processor", external_id="ext-002")
        # id2 now has ext-002; update id2 to ext-001 should work (id1 released)
        self.registry.update_external_id(id1, None)  # clear id1
        result = self.registry.update_external_id(id2, "ext-001")
        assert result is True
        assert self.registry.get(id2)["external_id"] == "ext-001"

    def test_delete_releases_external_id(self):
        """Deleting an agent frees its external_id for reuse."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        self.registry.delete(id1)
        id2 = self.registry.register("svc-b", "worker.processor", external_id="ext-001")
        assert id2 != id1

    def test_restore_agent_with_external_id(self):
        """Restore re-registers the external_id for the restored agent."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        self.registry.update_status(id1, AgentStatus.TERMINATED)
        self.registry.restore(id1)
        agent = self.registry.get(id1)
        assert agent["status"] == AgentStatus.PENDING.value
        assert agent["external_id"] == "ext-001"
        # ext-001 should still be registered to id1 (not released)
        assert self.registry.get_by_external_id("ext-001")["id"] == id1

    def test_restore_agent_blocked_when_active(self):
        """Restore returns False for agents not in a terminal state."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        result = self.registry.restore(id1)
        assert result is False  # still PENDING

    def test_get_by_external_id(self):
        """get_by_external_id returns the agent with the given external_id."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        agent = self.registry.get_by_external_id("ext-001")
        assert agent is not None
        assert agent["id"] == id1

    def test_get_by_external_id_nonexistent(self):
        """get_by_external_id returns None for unknown IDs."""
        assert self.registry.get_by_external_id("does-not-exist") is None

    def test_get_by_external_id_after_stopped(self):
        """get_by_external_id returns None once the agent is in a terminal state."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        self.registry.update_status(id1, AgentStatus.STOPPED)
        # ext-001 was released on transition to terminal state
        assert self.registry.get_by_external_id("ext-001") is None

    def test_multiple_external_ids_unique_per_active_agent(self):
        """Each active agent must have a unique external_id."""
        id1 = self.registry.register("svc-a", "worker.processor", external_id="ext-001")
        id2 = self.registry.register("svc-b", "worker.processor", external_id="ext-002")
        id3 = self.registry.register("svc-c", "worker.processor", external_id="ext-003")
        assert self.registry.get_by_external_id("ext-001")["id"] == id1
        assert self.registry.get_by_external_id("ext-002")["id"] == id2
        assert self.registry.get_by_external_id("ext-003")["id"] == id3
        # Now stop id2 and let id4 take ext-002
        self.registry.update_status(id2, AgentStatus.STOPPED)
        id4 = self.registry.register("svc-d", "worker.processor", external_id="ext-002")
        assert id4 != id2
        assert self.registry.get_by_external_id("ext-002")["id"] == id4
