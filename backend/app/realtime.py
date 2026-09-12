from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, list[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self.connections.get(user_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            self.connections.pop(user_id, None)

    async def broadcast(self, user_id: int, event: dict[str, str | int]) -> None:
        for websocket in self.connections.get(user_id, []).copy():
            try:
                await websocket.send_json(event)
            except RuntimeError:
                self.disconnect(user_id, websocket)


manager = ConnectionManager()
