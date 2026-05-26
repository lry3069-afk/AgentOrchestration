"""Task Scheduler — Priority-based task queuing and dispatch with fairness budgets."""

import asyncio
import heapq
import time
import logging
from typing import Any, Dict, Optional, List, Set
from uuid import uuid4
from enum import Enum

logger = logging.getLogger(__name__)


class PriorityClass(Enum):
    """Priority classes for fairness budget separation."""
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"


class FairnessBudgetExceededError(Exception):
    """Raised when a priority class has exhausted its fairness budget."""

    def __init__(self, priority_class: PriorityClass, budget: int, used: int):
        super().__init__(
            f"Fairness budget for {priority_class.value} exceeded "
            f"(budget={budget}, used={used})"
        )
        self.priority_class = priority_class
        self.budget = budget
        self.used = used


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class FairnessBudget:
    """Tracks usage of fairness budget per priority class.

    Each priority class gets a separate budget (e.g., number of tasks
    that can be dispatched in a time window).  Once the budget is
    exhausted, tasks of that class are deferred until the budget
    resets.
    """

    def __init__(
        self,
        budgets: Dict[PriorityClass, int],
        window_seconds: int = 60,
    ):
        self._budgets = budgets
        self._window = window_seconds
        # Maps priority_class -> list of (timestamp, task_id)
        self._usage: Dict[PriorityClass, List[float]] = {
            pc: [] for pc in PriorityClass
        }
        self._lock = asyncio.Lock()

    async def can_dispatch(
        self,
        priority_class: PriorityClass,
        task_id: str,
    ) -> bool:
        """Check if a task of given priority class can be dispatched.

        Returns True if budget is available, False otherwise.
        """
        async with self._lock:
            now = time.time()
            # Clean up old usage records
            cutoff = now - self._window
            self._usage[priority_class] = [
                ts for ts in self._usage[priority_class] if ts > cutoff
            ]
            budget = self._budgets.get(priority_class, 0)
            if budget <= 0:
                # Unlimited budget
                return True
            if len(self._usage[priority_class]) >= budget:
                logger.debug(
                    "Fairness budget exhausted for %s (budget=%d, used=%d)",
                    priority_class.value,
                    budget,
                    len(self._usage[priority_class]),
                )
                return False
            self._usage[priority_class].append(now)
            return True

    def reset(self, priority_class: Optional[PriorityClass] = None):
        """Reset usage for a priority class (or all)."""
        with self._lock:
            if priority_class is None:
                for pc in self._usage:
                    self._usage[pc].clear()
            else:
                self._usage[priority_class].clear()


class TaskScheduler:
    def __init__(
        self,
        fairness_budgets: Optional[Dict[PriorityClass, int]] = None,
        fairness_window: int = 60,
    ):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3

        # Fairness budget tracking
        if fairness_budgets is None:
            fairness_budgets = {
                PriorityClass.URGENT: 10,
                PriorityClass.HIGH: 20,
                PriorityClass.NORMAL: 50,
                PriorityClass.LOW: 100,
                PriorityClass.BACKGROUND: 200,
            }
        self._fairness = FairnessBudget(fairness_budgets, fairness_window)

        # Audit log for fairness decisions
        self._audit_log: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Enqueue / schedule with fairness budget check
    # ------------------------------------------------------------------

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
        priority_class: PriorityClass = PriorityClass.NORMAL,
    ) -> str:
        """Enqueue a task with a priority class for fairness budgeting."""
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["priority_class"] = priority_class.value
        task["priority"] = priority

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
        priority_class: PriorityClass = PriorityClass.NORMAL,
    ) -> str:
        """Schedule a task for future execution with fairness class."""
        task_id = str(uuid4())
        task["id"] = task_id
        task["priority_class"] = priority_class.value
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        """Dequeue a task, respecting fairness budgets per priority class.

        If the next task's priority class has exhausted its fairness
        budget, the task is skipped (remains in queue) and the next
        eligible task is returned.  If no eligible tasks are found,
        returns None.
        """
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(
                    task,
                    queue,
                    priority=task.get("priority", 0),
                    priority_class=PriorityClass(
                        task.get("priority_class", "normal")
                    ),
                )

        if queue not in self._queues or len(self._queues[queue]) == 0:
            return None

        # Peek at the highest-priority task
        peeked = self._queues[queue].peek()
        if peeked is None:
            return None

        # Determine its priority class
        pc_str = peeked.get("priority_class", "normal")
        try:
            pc = PriorityClass(pc_str)
        except ValueError:
            pc = PriorityClass.NORMAL

        # Check fairness budget
        can_dispatch = await self._fairness.can_dispatch(pc, peeked["id"])
        if not can_dispatch:
            # Budget exhausted — skip this task and try the next one
            # (We'll temporarily pop it, record the skip, and re-queue it
            #  at the same priority but with a bumped counter to avoid
            #  starvation.)
            skipped = self._queues[queue].pop()
            if skipped:
                # Record the skip for audit
                self._audit_log.append({
                    "timestamp": now,
                    "task_id": skipped["id"],
                    "priority_class": pc.value,
                    "action": "skipped_fairness_budget",
                    "queue": queue,
                })
                # Re-queue with same priority but slightly lower
                # to allow other tasks a chance
                self._queues[queue].push(skipped, skipped.get("priority", 0) - 1)
                logger.debug(
                    "Task %s (priority_class=%s) skipped due to fairness budget",
                    skipped["id"],
                    pc.value,
                )
            # Recursively try the next task
            return await self.dequeue(queue, timeout)

        # Budget available — dequeue normally
        task = self._queues[queue].pop()
        if task:
            self._in_flight[task["id"]] = task
            self._audit_log.append({
                "timestamp": now,
                "task_id": task["id"],
                "priority_class": pc.value,
                "action": "dispatched",
                "queue": queue,
            })
        return task

    # ------------------------------------------------------------------
    # Completion / failure
    # ------------------------------------------------------------------

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(
        self,
        task_id: str,
        queue: str = "default",
        priority_class: PriorityClass = PriorityClass.NORMAL,
    ) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(
                    task,
                    queue,
                    priority=task.get("priority", 0),
                    priority_class=priority_class,
                )
                return True
        return False

    # ------------------------------------------------------------------
    # Fairness budget management
    # ------------------------------------------------------------------

    def reset_fairness_budget(self, priority_class: Optional[PriorityClass] = None):
        """Reset fairness budget usage for a priority class (or all)."""
        self._fairness.reset(priority_class)

    def get_fairness_usage(self) -> Dict[str, Dict[str, int]]:
        """Return current fairness budget usage per priority class."""
        # This is a simplified view; the real FairnessBudget would expose
        # internal counters.
        return {
            pc.value: {"budget": self._fairness._budgets.get(pc, 0)}
            for pc in PriorityClass
        }

    def get_audit_log(
        self,
        limit: int = 100,
        priority_class: Optional[PriorityClass] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent fairness audit log entries."""
        filtered = self._audit_log
        if priority_class is not None:
            filtered = [
                e for e in filtered
                if e.get("priority_class") == priority_class.value
            ]
        return filtered[-limit:]

# 2026-05-26T11:00:00 update — separate fairness budgets by priority class (#4604)
