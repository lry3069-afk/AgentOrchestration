"""Agent Executor — Handles task execution within agent sandboxes."""

import asyncio
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4


class AgentExecutor:
    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, Any] = {}

    async def execute(self, agent_id: str, task: Dict[str, Any], handler: Callable) -> str:
        execution_id = str(uuid4())
        async with self._semaphore:
            task_obj = asyncio.create_task(
                self._run_execution(execution_id, agent_id, task, handler)
            )
            self._active_tasks[execution_id] = task_obj
            try:
                result = await task_obj
                self._results[execution_id] = result
            except Exception as e:
                self._results[execution_id] = {"error": str(e)}
            finally:
                self._active_tasks.pop(execution_id, None)
        return execution_id

    async def _run_execution(self, exec_id: str, agent_id: str, task: Dict, handler: Callable) -> Any:
        start = time.time()
        result = await handler(agent_id, task)
        duration = time.time() - start
        return {
            "execution_id": exec_id,
            "agent_id": agent_id,
            "task_id": task.get("id"),
            "result": result,
            "duration": duration,
            "timestamp": time.time(),
        }

    def get_result(self, execution_id: str) -> Optional[Any]:
        return self._results.get(execution_id)

    def cancel(self, execution_id: str) -> bool:
        task = self._active_tasks.get(execution_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def shutdown(self) -> None:
        for task in self._active_tasks.values():
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)

# 2019-01-31T14:19:34 update

# 2019-02-14T17:08:55 update

# 2019-03-28T08:28:18 update

# 2019-10-22T14:08:13 update

# 2020-01-02T11:41:47 update

# 2020-05-27T15:54:00 update

# 2020-06-03T11:28:30 update

# 2020-06-30T11:26:45 update

# 2020-07-22T16:27:48 update

# 2020-10-26T10:21:42 update

# 2020-12-11T08:18:01 update

# 2021-01-19T19:48:39 update

# 2021-02-11T20:31:28 update

# 2021-03-03T17:36:43 update

# 2021-04-13T12:11:10 update

# 2021-10-01T12:48:15 update

# 2021-10-11T13:15:06 update

# 2022-03-04T17:29:10 update
