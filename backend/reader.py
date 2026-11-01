"""Acceso al lector. Todo pasa por aquí para serializar las operaciones con un bloqueo."""
import threading

from smartcard.Exceptions import CardConnectionException, NoCardException, SmartcardException
from smartcard.System import readers
from smartcard.util import toBytes, toHexString

from backend import storage

GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
SW_OK = (0x90, 0x00)
KEY_TYPES = {"A": 0x60, "B": 0x61}

# Claves de fábrica públicas de MIFARE Classic
DEFAULT_KEYS = ["FFFFFFFFFFFF", "A0A1A2A3A4A5", "D3F7D3F7D3F7", "000000000000"]

# Bytes 13 y 14 del ATR que genera el lector según PC/SC
CARD_TYPES = {
    (0x00, 0x01): "MIFARE Classic 1K",
    (0x00, 0x02): "MIFARE Classic 4K",
    (0x00, 0x03): "MIFARE Ultralight",
    (0x00, 0x26): "MIFARE Mini",
}

# (primer bloque, bloques) de cada sector
SECTOR_LAYOUTS = {
    "MIFARE Mini": [(s * 4, 4) for s in range(5)],
    "MIFARE Classic 1K": [(s * 4, 4) for s in range(16)],
    "MIFARE Classic 4K": [(s * 4, 4) for s in range(32)] + [(128 + s * 16, 16) for s in range(8)],
}

_lock = threading.Lock()


class CardError(Exception):
    """Error que se puede mostrar directamente al usuario."""


def _card_type(atr: list[int]) -> str:
    if len(atr) < 15:
        return "Desconocida"
    return CARD_TYPES.get((atr[13], atr[14]), "Desconocida")


def _read_card(reader) -> dict | None:
    connection = reader.createConnection()
    try:
        connection.connect()
        atr = connection.getATR()
        data, sw1, sw2 = connection.transmit(GET_UID)
        return {
            "uid": toHexString(data) if (sw1, sw2) == SW_OK else None,
            "atr": toHexString(atr),
            "type": _card_type(atr),
        }
    except (NoCardException, CardConnectionException):
        return None
    finally:
        connection.release()


def status() -> dict:
    """Devuelve el lector conectado y la tarjeta presente, si los hay."""
    with _lock:
        try:
            found = readers()
            if not found:
                return {"reader": None, "card": None}
            return {"reader": str(found[0]), "card": _read_card(found[0])}
        except SmartcardException:
            return {"reader": None, "card": None}


def _authenticate(connection, block: int, key: str, key_type: str) -> bool:
    _, sw1, sw2 = connection.transmit([0xFF, 0x82, 0x00, 0x00, 0x06] + toBytes(key))
    if (sw1, sw2) != SW_OK:
        raise CardError("El lector no ha aceptado la clave")
    _, sw1, sw2 = connection.transmit(
        [0xFF, 0x86, 0x00, 0x00, 0x05, 0x01, 0x00, block, KEY_TYPES[key_type], 0x00]
    )
    if (sw1, sw2) == SW_OK:
        return True
    # Tras un fallo la tarjeta queda detenida: hay que volver a seleccionarla
    connection.disconnect()
    connection.connect()
    return False


def _find_key(connection, block: int, keys: list[str]) -> tuple[str, str] | None:
    for key in keys:
        for key_type in KEY_TYPES:
            if _authenticate(connection, block, key, key_type):
                return key, key_type
    return None


def _read_block(connection, block: int) -> str | None:
    data, sw1, sw2 = connection.transmit([0xFF, 0xB0, 0x00, block, 0x10])
    return toHexString(data) if (sw1, sw2) == SW_OK else None


def _block_kind(block: int, first_block: int, block_count: int) -> str:
    if block == 0:
        return "manufacturer"
    return "trailer" if block == first_block + block_count - 1 else "data"


def _read_sector(connection, number: int, first_block: int, block_count: int, keys: list[str]) -> dict:
    found = _find_key(connection, first_block, keys)
    blocks = range(first_block, first_block + block_count)
    return {
        "sector": number,
        "key": found[0] if found else None,
        "key_type": found[1] if found else None,
        "blocks": [
            {
                "block": block,
                "kind": _block_kind(block, first_block, block_count),
                "data": _read_block(connection, block) if found else None,
            }
            for block in blocks
        ],
    }


def read_card(extra_keys: list[str]) -> dict:
    """Lee todos los sectores posibles probando las claves indicadas y las de fábrica. No escribe."""
    keys = list(dict.fromkeys([key.upper() for key in extra_keys] + DEFAULT_KEYS))
    with _lock:
        try:
            found = readers()
            if not found:
                raise CardError("No hay ningún lector conectado")
            connection = found[0].createConnection()
            try:
                connection.connect()
                atr = connection.getATR()
                card_type = _card_type(atr)
                layout = SECTOR_LAYOUTS.get(card_type)
                if layout is None:
                    raise CardError(f"Tipo de tarjeta no compatible: {card_type}")
                data, sw1, sw2 = connection.transmit(GET_UID)
                sectors = [
                    _read_sector(connection, number, first_block, block_count, keys)
                    for number, (first_block, block_count) in enumerate(layout)
                ]
            finally:
                connection.release()
        except NoCardException as error:
            raise CardError("No hay ninguna tarjeta en el lector") from error
        except SmartcardException as error:
            raise CardError("Se ha perdido la tarjeta durante la lectura. Déjala quieta y repite.") from error
    return {
        "uid": toHexString(data) if (sw1, sw2) == SW_OK else None,
        "type": card_type,
        "sectors": sectors,
    }


def to_hex(data: list[int]) -> str:
    return toHexString(data)


def to_ascii(data: list[int]) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "\u00b7" for b in data)


def _sector_first_block(block: int, layout: list[tuple[int, int]]) -> int:
    for first_block, block_count in layout:
        if first_block <= block < first_block + block_count:
            return first_block
    return block


def writable_blocks(card_type: str) -> list[int]:
    """Bloques de datos: ni el bloque 0 (fabricante) ni los trailer (claves)."""
    layout = SECTOR_LAYOUTS.get(card_type)
    if layout is None:
        return []
    blocks = []
    for first_block, block_count in layout:
        for block in range(first_block, first_block + block_count):
            if _block_kind(block, first_block, block_count) == "data":
                blocks.append(block)
    return blocks


def plan_frames(mode: str, payload: str, start_block: int, card_type: str) -> list[tuple[int, list[int]]]:
    """Convierte el contenido del usuario en (bloque, 16 bytes). No toca el hardware."""
    allowed = writable_blocks(card_type)
    if not allowed:
        raise CardError(f"Tipo de tarjeta no compatible para escritura: {card_type}")
    if start_block not in allowed:
        raise CardError(f"El bloque {start_block} no es de datos. El bloque 0 y los trailer estan protegidos.")
    if mode == "hex":
        tokens = payload.replace(" ", "")
        if len(tokens) != 32 or any(c not in "0123456789abcdefABCDEF" for c in tokens):
            raise CardError("Introduce exactamente 16 bytes en hexadecimal (32 digitos).")
        data = [int(tokens[i:i + 2], 16) for i in range(0, 32, 2)]
        return [(start_block, data)]
    raw = payload.encode("utf-8")
    if not raw:
        raise CardError("Escribe algun contenido.")
    chunks = [list(raw[i:i + 16]) for i in range(0, len(raw), 16)]
    chunks[-1] = chunks[-1] + [0] * (16 - len(chunks[-1]))
    targets = [block for block in allowed if block >= start_block]
    if len(chunks) > len(targets):
        raise CardError(
            f"El texto ocupa {len(chunks)} bloques y desde el {start_block} solo quedan "
            f"{len(targets)} bloques de datos."
        )
    return list(zip(targets, chunks))


def _write_block(connection, block: int, data: list[int]) -> bool:
    _, sw1, sw2 = connection.transmit([0xFF, 0xD6, 0x00, block, 0x10] + data)
    return (sw1, sw2) == SW_OK


def write_blocks(frames: list[tuple[int, list[int]]], extra_keys: list[str]) -> dict:
    """Escribe en bloques de datos. Copia de seguridad antes y verificacion despues. Nunca toca bloque 0 ni trailer."""
    keys = list(dict.fromkeys([key.upper() for key in extra_keys] + DEFAULT_KEYS))
    with _lock:
        try:
            found = readers()
            if not found:
                raise CardError("No hay ningun lector conectado")
            connection = found[0].createConnection()
            try:
                connection.connect()
                card_type = _card_type(connection.getATR())
                layout = SECTOR_LAYOUTS.get(card_type)
                if layout is None:
                    raise CardError(f"Tipo de tarjeta no compatible para escritura: {card_type}")
                allowed = set(writable_blocks(card_type))
                for block, data in frames:
                    if block not in allowed:
                        raise CardError(f"El bloque {block} esta protegido y no se puede escribir.")
                    if len(data) != 16:
                        raise CardError(f"El bloque {block} no tiene 16 bytes.")
                uid_data, sw1, sw2 = connection.transmit(GET_UID)
                uid = toHexString(uid_data) if (sw1, sw2) == SW_OK else None

                backup = []
                for block, _data in frames:
                    if not _find_key(connection, _sector_first_block(block, layout), keys):
                        raise CardError(f"No hay clave valida para el sector del bloque {block}. Anade la clave correcta.")
                    backup.append({"block": block, "data": _read_block(connection, block)})
                backup_file = storage.save_backup(uid, card_type, backup)

                results = []
                for block, data in frames:
                    _find_key(connection, _sector_first_block(block, layout), keys)
                    ok = _write_block(connection, block, data)
                    after = _read_block(connection, block)
                    results.append({
                        "block": block,
                        "written": after,
                        "verified": bool(ok and after == toHexString(data)),
                    })
            finally:
                connection.release()
        except NoCardException as error:
            raise CardError("No hay ninguna tarjeta en el lector") from error
        except SmartcardException as error:
            raise CardError("Se perdio la tarjeta durante la escritura. Dejala quieta y repite.") from error
    return {"type": card_type, "uid": uid, "backup_file": backup_file, "results": results}
