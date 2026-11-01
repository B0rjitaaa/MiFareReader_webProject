import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend import reader

POLL_SECONDS = 0.5
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
ALLOWED_ORIGINS = {"http://localhost:8122", "http://127.0.0.1:8122"}

clients: set[WebSocket] = set()
current_status: dict = {"reader": None, "card": None}

HexKey = Annotated[str, StringConstraints(pattern=r"^[0-9A-Fa-f]{12}$")]


class ReadRequest(BaseModel):
    keys: list[HexKey] = Field(default=[], max_length=16)


async def monitor_reader() -> None:
    global current_status
    while True:
        new_status = await asyncio.to_thread(reader.status)
        if new_status != current_status:
            current_status = new_status
            for client in list(clients):
                try:
                    await client.send_json(new_status)
                except (WebSocketDisconnect, RuntimeError):
                    clients.discard(client)
        await asyncio.sleep(POLL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(monitor_reader())
    yield
    task.cancel()


app = FastAPI(title="MiFare Reader", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


def origin_allowed(origin: str | None) -> bool:
    # Los navegadores siempre envían Origin en estas peticiones: una web ajena queda fuera
    return origin is None or origin in ALLOWED_ORIGINS


@app.middleware("http")
async def reject_foreign_origin(request: Request, call_next):
    if not origin_allowed(request.headers.get("origin")):
        return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
    return await call_next(request)


@app.get("/api/status")
async def get_status() -> dict:
    return current_status


@app.post("/api/read")
async def read_card(request: ReadRequest) -> dict:
    try:
        return await asyncio.to_thread(reader.read_card, request.keys)
    except reader.CardError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.websocket("/ws/status")
async def status_socket(websocket: WebSocket) -> None:
    if not origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    clients.add(websocket)
    try:
        await websocket.send_json(current_status)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(websocket)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
