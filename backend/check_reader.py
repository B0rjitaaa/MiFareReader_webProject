"""Comprueba el acceso al lector: lista lectores y lee el UID. No escribe nada."""
from smartcard.CardRequest import CardRequest
from smartcard.CardType import AnyCardType
from smartcard.Exceptions import CardRequestTimeoutException
from smartcard.System import readers
from smartcard.util import toHexString

GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
TIMEOUT_SECONDS = 20


def main() -> int:
    found = readers()
    print(f"Lectores: {[str(r) for r in found]}")
    if not found:
        return 1

    try:
        service = CardRequest(timeout=TIMEOUT_SECONDS, cardType=AnyCardType()).waitforcard()
    except CardRequestTimeoutException:
        print(f"Sin tarjeta tras {TIMEOUT_SECONDS} s")
        return 2

    service.connection.connect()
    print(f"ATR: {toHexString(service.connection.getATR())}")
    data, sw1, sw2 = service.connection.transmit(GET_UID)
    print(f"UID: {toHexString(data)} (SW {sw1:02X} {sw2:02X})")
    service.connection.disconnect()
    return 0 if (sw1, sw2) == (0x90, 0x00) else 3


if __name__ == "__main__":
    raise SystemExit(main())
