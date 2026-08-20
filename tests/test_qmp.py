from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import BinaryIO, cast

import pytest

import dos_mcp.qmp
from dos_mcp.errors import QmpCommandError, QmpProtocolError, QmpTransportError
from dos_mcp.qmp import QmpClient, QmpSession


@contextmanager
def qmp_server(
    responses: list[dict[str, object] | None],
) -> Iterator[tuple[int, list[object]]]:
    received: list[object] = []
    ready = threading.Event()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        ready.set()
        connection, _ = listener.accept()
        with connection, connection.makefile("rwb") as stream:
            stream.write(b'{"QMP":{"version":{}}}\r\n')
            stream.flush()
            for response in responses:
                received.append(json.loads(stream.readline()))
                if response is None:
                    break
                stream.write(json.dumps(response).encode() + b"\r\n")
                stream.flush()
        listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    ready.wait()
    try:
        yield port, received
    finally:
        thread.join(timeout=2)
        listener.close()


def test_handshake_and_command() -> None:
    with qmp_server([{"return": {}}, {"return": {"status": "running"}}]) as (
        port,
        received,
    ):
        result = QmpClient(port, 1).execute("query-status")
    assert result == {"status": "running"}
    assert received == [
        {"execute": "qmp_capabilities"},
        {"execute": "query-status"},
    ]


def test_command_error() -> None:
    with qmp_server(
        [{"return": {}}, {"error": {"class": "GenericError", "desc": "no"}}]
    ) as (port, _), pytest.raises(QmpCommandError, match="GenericError: no"):
        QmpClient(port, 1).execute("stop")


def test_rejects_missing_return() -> None:
    with qmp_server([{"return": {}}, {"event": "STOP"}]) as (
        port,
        _,
    ), pytest.raises(QmpProtocolError, match="neither return nor error"):
        QmpClient(port, 1).execute("query-status")


def test_execute_many_is_sequential_and_paced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(dos_mcp.qmp.time, "sleep", sleeps.append)
    with qmp_server(
        [{"return": {}}, {"return": {"a": 1}}, {"return": {"b": 2}}]
    ) as (port, received):
        result = QmpClient(port, 1).execute_many(
            [("first", None), ("second", {"value": 2})],
            delay_seconds=0.02,
        )
    assert result == [{"a": 1}, {"b": 2}]
    assert received == [
        {"execute": "qmp_capabilities"},
        {"execute": "first"},
        {"execute": "second", "arguments": {"value": 2}},
    ]
    assert sleeps == [0.02]


def test_connect_error_is_a_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_connection(*args: object, **kwargs: object) -> socket.socket:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(socket, "create_connection", refuse_connection)
    with pytest.raises(QmpTransportError, match="127.0.0.1:4444.*refused"):
        QmpClient(4444, 1).execute("query-status")


def test_command_timeout_is_a_transport_error() -> None:
    class TimeoutStream:
        def write(self, payload: bytes) -> int:
            return len(payload)

        def flush(self) -> None:
            pass

        def readline(self, limit: int = -1) -> bytes:
            raise TimeoutError("timed out")

    stream = cast(BinaryIO, TimeoutStream())
    with pytest.raises(QmpTransportError, match="127.0.0.1:4444.*timed out"):
        QmpSession(stream, 4444).execute("query-status")


def test_command_eof_is_a_transport_error() -> None:
    with (
        qmp_server([{"return": {}}, None]) as (port, _),
        pytest.raises(QmpTransportError, match="127.0.0.1.*peer closed"),
    ):
        QmpClient(port, 1).execute("query-status")


def test_tool_body_oserror_is_not_relabelled() -> None:
    with (
        qmp_server([{"return": {}}]) as (port, _),
        pytest.raises(OSError, match="local file failed"),
        QmpClient(port, 1).session(),
    ):
        raise OSError("local file failed")
