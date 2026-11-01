import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend import reader, storage

POLL_SECONDS = 0.5
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "192.168.178.104", "pcmint-optiplex-3020m.fritz.box"]
ALLOWED_ORIGINS = {f"http://{host}:8122" for host in ALLOWED_HOSTS}

clients: set[WebSocket] = set()
current_status: dict = {"reader": None, "card": None}
last_reading: dict | None = None

HexKey = Annotated[str, StringConstraints(pattern=r"^[0-9A-Fa-f]{12}$")]
CardName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class ReadRequest(BaseModel):
    keys: list[HexKey] = Field(default=[], max_length=16)


class SaveRequest(BaseModel):
    name: CardName
    uid: str | None


class RenameRequest(BaseModel):
    name: CardName


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
    global last_reading
    try:
        reading = await asyncio.to_thread(reader.read_card, request.keys)
    except reader.CardError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    last_reading = {**reading, "read_at": datetime.now(timezone.utc).isoformat()}
    return last_reading


@app.get("/api/cards")
def list_cards() -> list[dict]:
    return storage.list_cards()


@app.post("/api/cards", status_code=201)
def save_card(request: SaveRequest) -> dict:
    # Solo se guarda una lectura hecha por el servidor, nunca datos enviados por el cliente
    if last_reading is None or last_reading["uid"] != request.uid:
        raise HTTPException(status_code=409, detail="Esa lectura ya no está disponible. Lee la tarjeta de nuevo.")
    try:
        return storage.save_card(request.name, last_reading)
    except storage.NameTaken as error:
        raise HTTPException(status_code=409, detail="Ya hay una tarjeta con ese nombre. Elige otro.") from error
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail="Ya existe esa tarjeta. Espera un segundo y repite.") from error


@app.get("/api/cards/{card_id}")
def get_card(card_id: str) -> dict:
    card = storage.load_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Tarjeta no encontrada")
    return card


@app.patch("/api/cards/{card_id}")
def rename_card(card_id: str, request: RenameRequest) -> dict:
    try:
        summary = storage.rename_card(card_id, request.name)
    except storage.NameTaken as error:
        raise HTTPException(status_code=409, detail="Ya hay una tarjeta con ese nombre. Elige otro.") from error
    if summary is None:
        raise HTTPException(status_code=404, detail="Tarjeta no encontrada")
    return summary


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
