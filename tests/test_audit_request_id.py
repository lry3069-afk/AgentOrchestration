"""Regression tests for Issue #4580 — Audit request ID preservation through async queue.

Acceptance criteria:
1. Audit events retain request ID after retries.
2. Missing request IDs are generated before enqueue.
3. Tests cover retry, dead-letter, and batch publish paths.
"""
import asyncio
import pytest
from src.orchestrator.scheduler import TaskScheduler


class TestAuditRequestIdPreservation:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    # ─────────────────────────────────────────────────────────────────────────
    # AC2: Missing request IDs are generated before enqueue
    # ─────────────────────────────────────────────────────────────────────────

    def test_request_id_generated_when_missing(self):
        """A task without request_id gets one assigned at enqueue time."""
        task_id = self.scheduler.enqueue({"type": "audit", "payload": {}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert "request_id" in task
        assert task["request_id"] is not None
        assert len(task["request_id"]) > 0

    def test_existing_request_id_preserved(self):
        """A task that already carries request_id keeps it unchanged."""
        fixed_rid = "fixed-correlation-id-12345"
        self.scheduler.enqueue({"type": "audit", "payload": {}, "request_id": fixed_rid})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["request_id"] == fixed_rid

    # ─────────────────────────────────────────────────────────────────────────
    # AC1: Audit events retain request ID after retries
    # ─────────────────────────────────────────────────────────────────────────

    def test_request_id_preserved_through_retry(self):
        """request_id survives from initial enqueue through retry to eventual completion."""
        self.scheduler.enqueue({"type": "audit", "payload": {}})
        import asyncio

        # First dequeue + fail (retry 1)
        task = asyncio.run(self.scheduler.dequeue())
        rid_after_fail1 = task["request_id"]
        assert self.scheduler.fail(task["id"]) is True

        # Second dequeue + fail (retry 2)
        task = asyncio.run(self.scheduler.dequeue())
        assert task["request_id"] == rid_after_fail1, "request_id changed after first retry"
        assert task["retries"] == 1
        assert self.scheduler.fail(task["id"]) is True

        # Third dequeue + fail (retry 3 = max, goes to dead-letter)
        task = asyncio.run(self.scheduler.dequeue())
        assert task["request_id"] == rid_after_fail1, "request_id changed after second retry"
        assert task["retries"] == 2
        self.scheduler.fail(task["id"])  # retries exhausted

        # Dead-lettered task must retain the same request_id
        dl_tasks = self.scheduler.get_dead_lettered()
        assert len(dl_tasks) == 1
        assert dl_tasks[0]["request_id"] == rid_after_fail1

    def test_retry_count_increments_correctly(self):
        """Retries counter increments each fail() call; exhausted retries goes to dead-letter."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        # dequeue once, fail → retries=0→1, stays alive
        task = asyncio.run(self.scheduler.dequeue())
        assert task["retries"] == 0
        assert self.scheduler.fail(task["id"]) is True
        # dequeue again, fail → retries=1→2, stays alive
        task = asyncio.run(self.scheduler.dequeue())
        assert task["retries"] == 1
        assert self.scheduler.fail(task["id"]) is True
        # dequeue again, fail → retries=2→3 == _max_retries → dead-letter, returns False
        task = asyncio.run(self.scheduler.dequeue())
        assert task["retries"] == 2
        assert self.scheduler.fail(task["id"]) is False
        # dead-lettered, queue empty
        assert asyncio.run(self.scheduler.dequeue()) is None

    def test_dead_letter_after_max_retries(self):
        """Task goes to dead-letter after exceeding _max_retries."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        while True:
            task = asyncio.run(self.scheduler.dequeue())
            if task is None:
                break
            if not self.scheduler.fail(task["id"]):
                break
        dl = self.scheduler.get_dead_lettered()
        assert len(dl) == 1

    # ─────────────────────────────────────────────────────────────────────────
    # Dead-letter path
    # ─────────────────────────────────────────────────────────────────────────

    def test_dead_letter_preserves_request_id(self):
        """Dead-lettered task carries its request_id for audit correlation."""
        rid = "audit-dead-letter-test"
        self.scheduler.enqueue({"type": "audit", "payload": {}, "request_id": rid})
        import asyncio
        while True:
            task = asyncio.run(self.scheduler.dequeue())
            if task is None:
                break
            if not self.scheduler.fail(task["id"]):
                break
        dl = self.scheduler.get_dead_lettered()
        assert len(dl) == 1
        assert dl[0]["request_id"] == rid
        assert "dead_lettered_at" in dl[0]

    def test_dead_letter_contains_no_in_flight(self):
        """Dead-lettered tasks are not in _in_flight."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])  # goes back to queue
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])  # exhausted → dead-letter
        assert len(self.scheduler._in_flight) == 0

    def test_dead_letter_multiple_tasks(self):
        """Multiple dead-lettered tasks each retain their own request_id."""
        self.scheduler.enqueue({"type": "a", "request_id": "dead-letter-A"})
        self.scheduler.enqueue({"type": "b", "request_id": "dead-letter-B"})
        import asyncio
        # Exhaust retries for each task individually
        while True:
            task_a = asyncio.run(self.scheduler.dequeue())
            if task_a is not None:
                if self.scheduler.fail(task_a["id"]):
                    continue  # still has retries left
            task_b = asyncio.run(self.scheduler.dequeue())
            if task_b is not None:
                if self.scheduler.fail(task_b["id"]):
                    continue  # still has retries left
            if task_a is None and task_b is None:
                break
        dl = self.scheduler.get_dead_lettered()
        rids = {t["request_id"] for t in dl}
        assert "dead-letter-A" in rids
        assert "dead-letter-B" in rids

    # ─────────────────────────────────────────────────────────────────────────
    # Batch publish path
    # ─────────────────────────────────────────────────────────────────────────

    def test_batch_enqueue_preserves_request_ids(self):
        """Batch-enqueued tasks each carry their own request_id."""
        tasks = [
            {"type": "batch", "payload": {"n": 1}},
            {"type": "batch", "payload": {"n": 2}},
            {"type": "batch", "payload": {"n": 3}},
        ]
        self.scheduler.enqueue_batch(tasks)

        import asyncio
        received = []
        for _ in range(len(tasks)):
            t = asyncio.run(self.scheduler.dequeue())
            received.append(t)

        # Each task must have its own request_id
        rids = [t["request_id"] for t in received]
        assert len(set(rids)) == len(rids), "Duplicate request_ids in batch"
        for t in received:
            assert "request_id" in t
            assert len(t["request_id"]) > 0

    def test_batch_with_preassigned_request_ids(self):
        """Batch-enqueue preserves explicitly-set request_ids."""
        tasks = [
            {"type": "batch", "request_id": "explicit-A"},
            {"type": "batch", "request_id": "explicit-B"},
        ]
        self.scheduler.enqueue_batch(tasks)
        import asyncio
        received = []
        for _ in range(len(tasks)):
            received.append(asyncio.run(self.scheduler.dequeue()))
        rids = [t["request_id"] for t in received]
        assert "explicit-A" in rids
        assert "explicit-B" in rids

    def test_batch_request_ids_survive_retry(self):
        """A request_id from a batch task survives retry."""
        tasks = [{"type": "batch-retry", "payload": {}}]
        self.scheduler.enqueue_batch(tasks)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        original_rid = task["request_id"]
        self.scheduler.fail(task["id"])
        task = asyncio.run(self.scheduler.dequeue())
        assert task["request_id"] == original_rid
