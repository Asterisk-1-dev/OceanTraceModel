from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await manager.send_json(
            websocket,
            {
                "type": "system_status",
                "mode": "DEMO",
                "message": "AQUAVIGIL WebSocket connected",
            },
        )
        while True:
            payload = await websocket.receive_text()
            await manager.send_json(websocket, {"type": "echo", "payload": payload})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
