from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BrowserAgentCommand:
    task_id: int | str | None
    job_id: int | str | None
    state: str
    action: str
    params: dict[str, Any]
    step_label: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "job_id": self.job_id,
            "state": self.state,
            "action": self.action,
            "params": dict(self.params),
            "step_label": self.step_label,
        }


def browser_agent_command_from_worker_request(
    request: dict[str, Any],
    *,
    step_label: str | None = None,
) -> BrowserAgentCommand:
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    return BrowserAgentCommand(
        task_id=request.get("task_id"),
        job_id=request.get("job_id"),
        state=str(request.get("state") or ""),
        action=str(request.get("action") or ""),
        params=dict(params),
        step_label=step_label,
    )
