"""Small synchronous client for DOSBox-X's loopback QMP subset."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager, suppress
from typing import Any, BinaryIO, cast

from .errors import QmpCommandError, QmpProtocolError, QmpTransportError

MAX_RESPONSE_BYTES = 24 * 1024 * 1024
Command = tuple[str, Mapping[str, object] | None]


class QmpClient:
    """Open a fresh, serialized QMP session for each public tool call."""

    def __init__(self, port: int, timeout: float) -> None:
        self._port = port
        self._timeout = timeout
        self._lock = threading.Lock()

    def execute(
        self,
        command: str,
        arguments: Mapping[str, object] | None = None,
    ) -> object:
        return self.execute_many([(command, arguments)])[0]

    def execute_many(
        self,
        commands: Sequence[Command],
        *,
        delay_seconds: float = 0,
    ) -> list[object]:
        if not commands:
            return []
        with self.session() as session:
            return session.execute_many(commands, delay_seconds=delay_seconds)

    @contextmanager
    def session(self) -> Iterator[QmpSession]:
        """Hold the client lock and one QMP connection for an atomic tool call."""

        with self._lock:
            resources = ExitStack()
            try:
                connection = resources.enter_context(
                    socket.create_connection(
                        ("127.0.0.1", self._port), timeout=self._timeout
                    )
                )
                connection.settimeout(self._timeout)
                raw_stream = resources.enter_context(connection.makefile("rwb"))
                stream = cast(BinaryIO, raw_stream)
                greeting = self._read_object(stream)
                if not isinstance(greeting.get("QMP"), dict):
                    raise QmpProtocolError("QMP greeting is missing")
                self._write_object(stream, {"execute": "qmp_capabilities"})
                self._return_value(self._read_object(stream))
            except (QmpCommandError, QmpProtocolError):
                resources.close()
                raise
            except (OSError, TimeoutError) as error:
                resources.close()
                raise QmpTransportError(
                    f"DOSBox-X QMP at 127.0.0.1:{self._port} failed: {error}"
                ) from error

            try:
                yield QmpSession(stream, self._port)
            except BaseException:
                with suppress(OSError):
                    resources.close()
                raise
            else:
                try:
                    resources.close()
                except (OSError, TimeoutError) as error:
                    raise QmpTransportError(
                        f"DOSBox-X QMP at 127.0.0.1:{self._port} failed: {error}"
                    ) from error

    @staticmethod
    def _write_object(stream: BinaryIO, value: Mapping[str, object]) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\r\n"
        stream.write(payload)
        stream.flush()

    @staticmethod
    def _read_object(stream: BinaryIO) -> dict[str, Any]:
        line = stream.readline(MAX_RESPONSE_BYTES + 1)
        if not line:
            raise ConnectionError("QMP peer closed before replying")
        if len(line) > MAX_RESPONSE_BYTES or not line.endswith(b"\n"):
            raise QmpProtocolError("QMP response exceeds the size limit")
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise QmpProtocolError("QMP response is not valid JSON") from error
        if not isinstance(value, dict):
            raise QmpProtocolError("QMP response must be an object")
        return value

    @staticmethod
    def _return_value(response: Mapping[str, object]) -> object:
        error = response.get("error")
        if isinstance(error, dict):
            error_class = error.get("class", "GenericError")
            description = error.get("desc", "QMP command failed")
            raise QmpCommandError(str(error_class), str(description))
        if "return" not in response:
            raise QmpProtocolError("QMP response has neither return nor error")
        return response["return"]


class QmpSession:
    """A handshaken connection owned by one QmpClient session context."""

    def __init__(self, stream: BinaryIO, port: int) -> None:
        self._stream = stream
        self._port = port

    def execute(
        self,
        command: str,
        arguments: Mapping[str, object] | None = None,
    ) -> object:
        return self.execute_many([(command, arguments)])[0]

    def execute_many(
        self,
        commands: Sequence[Command],
        *,
        delay_seconds: float = 0,
    ) -> list[object]:
        # DOSBox-X discards pipelined JSON after the first object. Keep this
        # strictly request/response: write one command, then read one reply.
        try:
            results: list[object] = []
            for name, arguments in commands:
                request: dict[str, object] = {"execute": name}
                if arguments is not None:
                    request["arguments"] = dict(arguments)
                QmpClient._write_object(self._stream, request)
                response = QmpClient._read_object(self._stream)
                results.append(QmpClient._return_value(response))
                if delay_seconds and len(results) < len(commands):
                    time.sleep(delay_seconds)
            return results
        except (OSError, TimeoutError) as error:
            raise QmpTransportError(
                f"DOSBox-X QMP at 127.0.0.1:{self._port} failed: {error}"
            ) from error
