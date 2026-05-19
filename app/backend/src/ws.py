from __future__ import annotations

from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.connections: dict[int, list[WebSocket]] = defaultdict(list)

    async def connect(self, task_id: int, websocket: WebSocket):
        await websocket.accept()
        self.connections[task_id].append(websocket)

    def disconnect(self, task_id: int, websocket: WebSocket):
        if websocket in self.connections[task_id]:
            self.connections[task_id].remove(websocket)

    async def broadcast(self, task_id: int, payload: dict):
        stale = []
        for websocket in self.connections[task_id]:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(task_id, websocket)
