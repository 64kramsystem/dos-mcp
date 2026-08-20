from __future__ import annotations

import base64
from contextlib import nullcontext
from pathlib import Path
from typing import cast

import pytest

from dos_mcp.errors import QmpProtocolError, RequestError
from dos_mcp.qmp import Command, QmpClient
from dos_mcp.tools import (
    capture_screen,
    key_event,
    load_state,
    pause,
    read_memory,
    resume,
    save_state,
    send_keys,
    swap_floppy,
    type_text,
)


class FakeClient:
    def __init__(
        self,
        response: object = None,
        status_response: object = None,
    ) -> None:
        self.response = {} if response is None else response
        self.status_response = (
            {"running": True, "emulator-paused": False}
            if status_response is None
            else status_response
        )
        self.calls: list[Command] = []

    def execute(
        self, command: str, arguments: dict[str, object] | None = None
    ) -> object:
        self.calls.append((command, arguments))
        if command == "query-status":
            return self.status_response
        return self.response

    def execute_many(
        self, commands: list[Command], *, delay_seconds: float = 0
    ) -> list[object]:
        assert delay_seconds == 0.02
        self.calls.extend(commands)
        return [{} for _ in commands]

    def session(self) -> object:
        return nullcontext(self)


def client(fake: FakeClient) -> QmpClient:
    return cast(QmpClient, fake)


def test_type_text_maps_shift_and_enter() -> None:
    fake = FakeClient()
    result = type_text(client(fake), "A!", press_enter=True)
    assert result["characters"] == 2
    assert fake.calls[1:] == [
        (
            "send-key",
            {
                "keys": [
                    {"type": "qcode", "data": "shift"},
                    {"type": "qcode", "data": "a"},
                ]
            },
        ),
        (
            "send-key",
            {
                "keys": [
                    {"type": "qcode", "data": "shift"},
                    {"type": "qcode", "data": "1"},
                ]
            },
        ),
        ("send-key", {"keys": [{"type": "qcode", "data": "ret"}]}),
    ]


@pytest.mark.parametrize(
    ("text", "press_enter", "message"),
    [("", False, "empty"), ("x" * 129, False, "exceeds")],
)
def test_type_text_bounds(text: str, press_enter: bool, message: str) -> None:
    with pytest.raises(RequestError, match=message):
        type_text(client(FakeClient()), text, press_enter=press_enter)


def test_send_keys_rejects_unknown_qcode() -> None:
    with pytest.raises(RequestError, match="unsupported qcode"):
        send_keys(client(FakeClient()), ["not-a-key"])


def test_input_rejects_paused_execution() -> None:
    paused = {"running": False, "emulator-paused": True}
    with pytest.raises(RequestError, match="requires running"):
        send_keys(client(FakeClient(status_response=paused)), ["a"])


def test_swap_floppy_validates_and_sends_qmp_command() -> None:
    fake = FakeClient()
    assert swap_floppy(client(fake), drive=0) == {"ok": True, "drive": 0}
    assert fake.calls[-1] == ("swap-floppy", {"drive": 0})

    with pytest.raises(RequestError, match="drive must be"):
        swap_floppy(client(FakeClient()), drive=2)


def test_read_memory_verifies_length() -> None:
    encoded = base64.b64encode(b"abc").decode()
    paused = {"running": False, "emulator-paused": True}
    result = read_memory(
        client(FakeClient({"data": encoded}, paused)), 0x100, 3
    )
    assert result["data_hex"] == "616263"
    assert result["size"] == 3
    assert result["consistent"] is True

    with pytest.raises(QmpProtocolError, match="instead of"):
        read_memory(client(FakeClient({"data": encoded}, paused)), 0x100, 4)


def test_read_memory_requires_pause_by_default() -> None:
    encoded = base64.b64encode(b"a").decode()
    fake = FakeClient({"data": encoded})
    with pytest.raises(RequestError, match="allow_running"):
        read_memory(client(fake), 0x100, 1)

    result = read_memory(client(fake), 0x100, 1, allow_running=True)
    assert result["consistent"] is False


def test_read_memory_rejects_server_integer_overflow() -> None:
    with pytest.raises(RequestError, match="0x7fffffff"):
        read_memory(client(FakeClient()), 0x80000000, 1)


def test_read_memory_file_output_and_overwrite(tmp_path: Path) -> None:
    class FileClient(FakeClient):
        def execute(
            self, command: str, arguments: dict[str, object] | None = None
        ) -> object:
            result = super().execute(command, arguments)
            if command == "memdump":
                assert arguments is not None
                Path(str(arguments["file"])).write_bytes(b"abc")
                return {"file": arguments["file"], "size": 3}
            return result

    paused = {"running": False, "emulator-paused": True}
    destination = tmp_path / "memory.bin"
    result = read_memory(
        client(FileClient(status_response=paused)),
        0x100,
        3,
        output_path=str(destination),
    )
    assert result["file"] == str(destination)
    assert destination.read_bytes() == b"abc"

    with pytest.raises(RequestError, match="already exists"):
        read_memory(
            client(FileClient(status_response=paused)),
            0x100,
            3,
            output_path=str(destination),
        )


def test_output_path_error_uses_output_wording() -> None:
    with pytest.raises(RequestError, match="output path must be absolute"):
        read_memory(
            client(FakeClient()),
            0x100,
            1,
            output_path="memory.bin",
        )


def test_save_state_requires_absolute_nonexistent_path(tmp_path: Path) -> None:
    with pytest.raises(RequestError, match="absolute"):
        save_state(client(FakeClient()), "state.zip", overwrite=False)

    destination = tmp_path / "state.zip"
    result = save_state(client(FakeClient()), str(destination), overwrite=False)
    assert result == {"ok": True, "file": str(destination)}

    destination.write_bytes(b"existing")
    with pytest.raises(RequestError, match="already exists"):
        save_state(client(FakeClient()), str(destination), overwrite=False)


def test_load_state_classifies_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RequestError, match="unavailable"):
        load_state(client(FakeClient()), str(tmp_path / "missing.zip"))


def test_state_path_rejects_non_ascii(tmp_path: Path) -> None:
    with pytest.raises(RequestError, match="unsupported"):
        save_state(client(FakeClient()), str(tmp_path / "café.zip"), overwrite=False)


def test_key_event_sends_explicit_make_and_break() -> None:
    fake = FakeClient()
    result = key_event(client(fake), "ctrl", down=True)
    assert result == {"ok": True, "key": "ctrl", "down": True}
    assert fake.calls[-1] == (
        "input-send-event",
        {
            "events": [
                {
                    "type": "key",
                    "data": {
                        "down": True,
                        "key": {"type": "qcode", "data": "ctrl"},
                    },
                }
            ]
        },
    )


def test_capture_screen_returns_valid_png() -> None:
    png = b"\x89PNG\r\n\x1a\ncontent"
    encoded = base64.b64encode(png).decode()
    assert capture_screen(client(FakeClient({"data": encoded}))) == png

    invalid = base64.b64encode(b"not png").decode()
    with pytest.raises(QmpProtocolError, match="did not return a PNG"):
        capture_screen(client(FakeClient({"data": invalid})))


def test_pause_and_resume_idempotent_branches() -> None:
    paused = {"running": False, "emulator-paused": True, "status": "paused"}
    pause_result = pause(client(FakeClient(status_response=paused)))
    assert pause_result == {
        "ok": True,
        "status": "paused",
        "running": False,
        "already_paused": True,
    }

    running = {"running": True, "emulator-paused": False, "status": "running"}
    result = resume(client(FakeClient(status_response=running)))
    assert result == {
        "ok": True,
        "status": "running",
        "running": True,
        "already_running": True,
    }


def test_resume_reports_remaining_gdb_pause() -> None:
    class StatusSequenceClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.states = [
                {"running": False, "emulator-paused": True, "status": "paused"},
                {"running": False, "emulator-paused": False, "status": "paused"},
            ]

        def execute(
            self, command: str, arguments: dict[str, object] | None = None
        ) -> object:
            self.calls.append((command, arguments))
            if command == "query-status":
                return self.states.pop(0)
            return {}

    result = resume(client(StatusSequenceClient()))
    assert result == {
        "ok": True,
        "status": "paused",
        "running": False,
        "already_running": False,
    }
