"""Task Scheduler 鈥?Priority-based task queuing and dispatch with separate lanes."""

import asyncio
import heapq
import time
from typing import Any, Dict, Optional
from uuid import uuid4


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


class TaskScheduler:
    def __init__(self):
        # Separate lanes: immediate tasks go to _immediate_queues,
        # scheduled tasks go to _scheduled_queues after their delay expires
        self._immediate_queues: Dict[str, PriorityQueue] = {}
        self._scheduled_queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
        scheduled: bool = False,
    ) -> str:
        """Enqueue a task. If scheduled=True, it goes to the scheduled lane."""
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["lane"] = "scheduled" if scheduled else "immediate"

        if scheduled:
            if queue not in self._scheduled_queues:
                self._scheduled_queues[queue] = PriorityQueue()
            self._scheduled_queues[queue].push(task, priority)
        else:
            if queue not in self._immediate_queues:
                self._immediate_queues[queue] = PriorityQueue()
            self._immediate_queues[queue].push(task, priority)
        return task_id

    def schedule(
        self, task: Dict, delay: float, queue: str = "default", priority: int = 0
    ) -> str:
        """Schedule a task for future execution. Goes to scheduled lane after delay."""
        task_id = str(uuid4())
        task["id"] = task_id
        task["lane"] = "scheduled"
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(
        self, queue: str = "default", timeout: float = 1.0
    ) -> Optional[Dict]:
        """Dequeue a task, prioritizing immediate lane over scheduled lane."""
        now = time.time()

        # Move expired scheduled tasks into the scheduled lane queue
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                if queue not in self._scheduled_queues:
                    self._scheduled_queues[queue] = PriorityQueue()
                self._scheduled_queues[queue].push(
                    task, task.get("priority", 0)
                )

        # Priority 1: immediate lane
        if queue in self._immediate_queues and len(self._immediate_queues[queue]) > 0:
            task = self._immediate_queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                return task

        # Priority 2: scheduled lane
        if queue in self._scheduled_queues and len(self._scheduled_queues[queue]) > 0:
            task = self._scheduled_queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                return task

        return None

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                # Re-enqueue to the same lane
                is_scheduled = task.get("lane") == "scheduled"
                self.enqueue(
                    task, queue, priority=task.get("priority", 0), scheduled=is_scheduled
                )
                return True
        return False