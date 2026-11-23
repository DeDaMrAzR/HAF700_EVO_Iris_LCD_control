# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at https://mozilla.org/MPL/2.0/.

"""Check the Iris port forward through the local ADB server."""

import socket


def _read(connection: socket.socket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        block = connection.recv(count - len(data))
        if not block:
            raise ConnectionError("ADB closed the connection")
        data.extend(block)
    return bytes(data)


def _select(connection: socket.socket, service: str) -> None:
    request = service.encode("ascii")
    connection.sendall(f"{len(request):04x}".encode("ascii") + request)
    status = _read(connection, 4)
    if status == b"FAIL":
        error = _read(connection, int(_read(connection, 4), 16)).decode("utf-8", errors="replace")
        raise ConnectionError(error)
    if status != b"OKAY":
        raise ConnectionError(f"Unexpected ADB response: {status!r}")


def has_forward(serial: str, local_port: int, remote_port: int) -> bool:
    """Ask the running server about this exact forward without starting ADB."""
    with socket.create_connection(("127.0.0.1", 5037), timeout=0.25) as connection:
        _select(connection, "host:list-forward")
        listing = _read(connection, int(_read(connection, 4), 16))
    expected = f"{serial} tcp:{local_port} tcp:{remote_port}".encode("ascii")
    return expected in listing.splitlines()
