"""Bounded DOSBox-X operations used by the MCP surface."""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Sequence
from pathlib import Path

from .errors import QmpProtocolError, RequestError
from .qmp import Command, QmpClient, QmpSession

QmpExecutor = QmpClient | QmpSession

MAX_MEMORY_READ = 64 * 1024
MAX_INLINE_MEMORY_READ = 4 * 1024
MAX_TYPED_TEXT = 128
MAX_KEY_CHORD = 8
KEY_DELAY_SECONDS = 0.02

QKEY_CODES = frozenset(
    {
        *(str(number) for number in range(10)),
        *(chr(letter) for letter in range(ord("a"), ord("z") + 1)),
        *(f"f{number}" for number in range(1, 25)),
        "shift",
        "shift_r",
        "ctrl",
        "ctrl_r",
        "alt",
        "alt_r",
        "meta_l",
        "meta_r",
        "menu",
        "esc",
        "tab",
        "backspace",
        "ret",
        "spc",
        "caps_lock",
        "num_lock",
        "scroll_lock",
        "grave_accent",
        "minus",
        "equal",
        "backslash",
        "bracket_left",
        "bracket_right",
        "semicolon",
        "apostrophe",
        "comma",
        "dot",
        "slash",
        "less",
        "insert",
        "delete",
        "home",
        "end",
        "pgup",
        "pgdn",
        "left",
        "right",
        "up",
        "down",
        *(f"kp_{number}" for number in range(10)),
        "kp_divide",
        "kp_multiply",
        "kp_subtract",
        "kp_add",
        "kp_enter",
        "kp_decimal",
        "kp_equals",
        "kp_comma",
        "print",
        "sysrq",
        "pause",
        "henkan",
        "muhenkan",
        "hiragana",
        "yen",
        "ro",
    }
)

_PLAIN_TEXT_KEYS = {
    " ": "spc",
    "\n": "ret",
    "\t": "tab",
    "\b": "backspace",
    "`": "grave_accent",
    "-": "minus",
    "=": "equal",
    "\\": "backslash",
    "[": "bracket_left",
    "]": "bracket_right",
    ";": "semicolon",
    "'": "apostrophe",
    ",": "comma",
    ".": "dot",
    "/": "slash",
}
_SHIFT_TEXT_KEYS = {
    "~": "grave_accent",
    "_": "minus",
    "+": "equal",
    "|": "backslash",
    "{": "bracket_left",
    "}": "bracket_right",
    ":": "semicolon",
    '"': "apostrophe",
    "<": "comma",
    ">": "dot",
    "?": "slash",
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
}


def status(client: QmpExecutor) -> dict[str, object]:
    return _object(client.execute("query-status"), "query-status")


def pause(client: QmpClient) -> dict[str, object]:
    with client.session() as session:
        state = status(session)
        if state.get("emulator-paused") is True:
            return {
                "ok": True,
                "status": state.get("status", "paused"),
                "running": state.get("running", False),
                "already_paused": True,
            }
        if state.get("running") is not True:
            raise RequestError("execution is paused by GDB; use GDB to control it")
        session.execute("stop")
        after = status(session)
        return {
            "ok": True,
            "status": after.get("status", "paused"),
            "running": after.get("running", False),
            "already_paused": False,
        }


def resume(client: QmpClient) -> dict[str, object]:
    with client.session() as session:
        state = status(session)
        if state.get("running") is True:
            return {
                "ok": True,
                "status": state.get("status", "running"),
                "running": True,
                "already_running": True,
            }
        if state.get("emulator-paused") is not True:
            raise RequestError("execution is paused by GDB; continue it through GDB")
        session.execute("cont")
        after = status(session)
        return {
            "ok": True,
            "status": after.get("status", "paused"),
            "running": after.get("running", False),
            "already_running": False,
        }


def reset(client: QmpClient, *, dos_only: bool) -> dict[str, object]:
    with client.session() as session:
        _require_running(session, "reset")
        session.execute("system_reset", {"dos_only": dos_only})
    return {"ok": True, "dos_only": dos_only}


def break_on_next_exec(client: QmpClient, *, enabled: bool) -> dict[str, object]:
    return _object(
        client.execute("debug-break-on-exec", {"enabled": enabled}),
        "debug-break-on-exec",
    )


def send_keys(client: QmpClient, keys: Sequence[str]) -> dict[str, object]:
    key_list = list(keys)
    if not key_list or len(key_list) > MAX_KEY_CHORD:
        raise RequestError(f"keys must contain 1 to {MAX_KEY_CHORD} qcodes")
    unknown = [key for key in key_list if key not in QKEY_CODES]
    if unknown:
        raise RequestError(f"unsupported qcode: {unknown[0]}")
    with client.session() as session:
        _require_running(session, "keyboard input")
        session.execute("send-key", {"keys": _qmp_keys(key_list)})
    return {"ok": True, "keys": key_list}


def key_event(client: QmpClient, key: str, *, down: bool) -> dict[str, object]:
    if key not in QKEY_CODES:
        raise RequestError(f"unsupported qcode: {key}")
    with client.session() as session:
        _require_running(session, "keyboard input")
        session.execute(
            "input-send-event",
            {
                "events": [
                    {
                        "type": "key",
                        "data": {
                            "down": down,
                            "key": {"type": "qcode", "data": key},
                        },
                    }
                ]
            },
        )
    return {"ok": True, "key": key, "down": down}


def type_text(client: QmpClient, text: str, *, press_enter: bool) -> dict[str, object]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized and not press_enter:
        raise RequestError("text is empty and press_enter is false")
    if len(normalized) > MAX_TYPED_TEXT:
        raise RequestError(f"text exceeds {MAX_TYPED_TEXT} characters")
    commands: list[Command] = []
    for character in normalized:
        commands.append(("send-key", {"keys": _qmp_keys(_text_keys(character))}))
    if press_enter:
        commands.append(("send-key", {"keys": _qmp_keys(["ret"])}))
    with client.session() as session:
        _require_running(session, "keyboard input")
        # The DOSBox-X QMP server drains its whole event queue in one main-loop
        # pass. Pacing prevents the finite emulated keyboard buffer from being
        # cleared on overflow. The guest must still consume its BIOS ring
        # buffer; text sent to a busy program can be dropped there.
        session.execute_many(commands, delay_seconds=KEY_DELAY_SECONDS)
    return {
        "ok": True,
        "characters": len(normalized),
        "pressed_enter": press_enter,
    }


def read_memory(
    client: QmpClient,
    address: int,
    size: int,
    *,
    output_path: str | None = None,
    overwrite: bool = False,
    allow_running: bool = False,
) -> dict[str, object]:
    if address < 0 or address > 0x7FFFFFFF:
        raise RequestError("address must be between 0 and 0x7fffffff")
    if size <= 0 or size > MAX_MEMORY_READ:
        raise RequestError(f"size must be between 1 and {MAX_MEMORY_READ}")
    if address + size > 0x8000_0000:
        raise RequestError("memory range exceeds DOSBox-X's QMP address range")
    arguments: dict[str, object] = {"address": address, "size": size}
    destination: Path | None = None
    if output_path is not None:
        destination = _output_path(output_path, overwrite=overwrite)
        arguments["file"] = str(destination)
    elif size > MAX_INLINE_MEMORY_READ:
        raise RequestError(
            f"inline reads are limited to {MAX_INLINE_MEMORY_READ} bytes; "
            "provide output_path for a larger read"
        )
    with client.session() as session:
        state = status(session)
        consistent = state.get("running") is not True
        if not consistent and not allow_running:
            raise RequestError(
                "memory can change during the read; pause DOSBox-X or pass "
                "allow_running=true"
            )
        response = _object(session.execute("memdump", arguments), "memdump")
    if destination is not None:
        try:
            data = destination.read_bytes()
        except OSError as error:
            raise QmpProtocolError(f"cannot read memdump output: {error}") from error
        if len(data) != size:
            raise QmpProtocolError(
                f"memdump wrote {len(data)} bytes instead of the requested {size}"
            )
        return {
            "address": address,
            "size": size,
            "sha256": hashlib.sha256(data).hexdigest(),
            "file": str(destination),
            "consistent": consistent,
        }

    encoded = response.get("data")
    if not isinstance(encoded, str):
        raise QmpProtocolError("memdump response is missing base64 data")
    data = _decode_base64(encoded, "memdump")
    if len(data) != size:
        raise QmpProtocolError(
            f"memdump returned {len(data)} bytes instead of the requested {size}"
        )
    return {
        "address": address,
        "size": size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_hex": data.hex(),
        "consistent": consistent,
    }


def capture_screen(client: QmpClient) -> bytes:
    with client.session() as session:
        _require_running(session, "screen capture")
        response = _object(session.execute("screendump"), "screendump")
    encoded = response.get("data")
    if not isinstance(encoded, str):
        raise QmpProtocolError("screendump response is missing base64 data")
    data = _decode_base64(encoded, "screendump")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise QmpProtocolError("screendump did not return a PNG")
    return data


def save_state(client: QmpClient, path: str, *, overwrite: bool) -> dict[str, object]:
    destination = _qmp_path(path, label="state", must_exist=False)
    if destination.is_dir():
        raise RequestError("state path names a directory")
    if destination.exists() and not overwrite:
        raise RequestError(
            "state file already exists; pass overwrite=true to replace it"
        )
    if not destination.parent.is_dir():
        raise RequestError("state file parent directory does not exist")
    with client.session() as session:
        _require_running(session, "state save")
        response = _object(
            session.execute("savestate", {"file": str(destination)}), "savestate"
        )
    return {"ok": True, "file": response.get("file", str(destination))}


def load_state(client: QmpClient, path: str) -> dict[str, object]:
    source = _qmp_path(path, label="state", must_exist=True)
    with client.session() as session:
        _require_running(session, "state load")
        response = _object(
            session.execute("loadstate", {"file": str(source)}), "loadstate"
        )
    return {"ok": True, "file": response.get("file", str(source))}


def _qmp_keys(keys: Sequence[str]) -> list[dict[str, str]]:
    return [{"type": "qcode", "data": key} for key in keys]


def _text_keys(character: str) -> list[str]:
    if "a" <= character <= "z" or "0" <= character <= "9":
        return [character]
    if "A" <= character <= "Z":
        return ["shift", character.lower()]
    if character in _PLAIN_TEXT_KEYS:
        return [_PLAIN_TEXT_KEYS[character]]
    if character in _SHIFT_TEXT_KEYS:
        return ["shift", _SHIFT_TEXT_KEYS[character]]
    raise RequestError(f"text contains unsupported US-ASCII character {character!r}")


def _object(value: object, command: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise QmpProtocolError(f"{command} response must be an object")
    return value


def _decode_base64(encoded: str, command: str) -> bytes:
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise QmpProtocolError(f"{command} returned invalid base64") from error


def _qmp_path(value: str, *, label: str, must_exist: bool) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RequestError(f"{label} path must be absolute")
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in str(path)):
        raise RequestError(
            f"{label} path contains a character unsupported by DOSBox-X QMP"
        )
    if '"' in str(path) or "\\" in str(path):
        raise RequestError(
            f"{label} path contains a character unsupported by DOSBox-X QMP"
        )
    try:
        resolved = path.resolve(strict=must_exist)
    except OSError as error:
        raise RequestError(f"{label} path is unavailable: {error}") from error
    if must_exist and not resolved.is_file():
        raise RequestError(f"{label} path is not a regular file")
    return resolved


def _output_path(value: str, *, overwrite: bool) -> Path:
    path = _qmp_path(value, label="output", must_exist=False)
    if path.exists() and not overwrite:
        raise RequestError(
            "output file already exists; pass overwrite=true to replace it"
        )
    if path.is_dir():
        raise RequestError("output path names a directory")
    if not path.parent.is_dir():
        raise RequestError("output file parent directory does not exist")
    return path


def _require_running(client: QmpExecutor, operation: str) -> None:
    state = status(client)
    if state.get("running") is not True:
        raise RequestError(
            f"{operation} requires running execution; resume DOSBox-X or "
            "continue it through GDB first"
        )
