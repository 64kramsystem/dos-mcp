"""MCP server construction."""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP, Image

from .config import Settings
from .qmp import QmpClient
from .tools import (
    break_on_next_exec,
    capture_screen,
    key_event,
    load_state,
    pause,
    read_memory,
    reset,
    resume,
    save_state,
    send_keys,
    status,
    type_text,
)


def create_server(settings: Settings, client: QmpClient | None = None) -> FastMCP:
    """Create the stdio server without opening the QMP connection."""

    qmp = client or QmpClient(settings.qmp_port, settings.qmp_timeout)
    server = FastMCP("dos-mcp")

    @server.tool()
    async def dosbox_status() -> dict[str, object]:
        """Report DOSBox-X run and debugger state."""

        return await asyncio.to_thread(status, qmp)

    @server.tool()
    async def dosbox_pause() -> dict[str, object]:
        """Pause DOSBox-X execution."""

        return await asyncio.to_thread(pause, qmp)

    @server.tool()
    async def dosbox_resume() -> dict[str, object]:
        """Resume DOSBox-X execution."""

        return await asyncio.to_thread(resume, qmp)

    @server.tool()
    async def dosbox_reset(dos_only: bool = False) -> dict[str, object]:
        """Reset the DOS guest, optionally without a full machine reset."""

        return await asyncio.to_thread(reset, qmp, dos_only=dos_only)

    @server.tool()
    async def dosbox_break_on_next_exec(enabled: bool = True) -> dict[str, object]:
        """Break GDB at the next DOS EXEC entry point."""

        return await asyncio.to_thread(break_on_next_exec, qmp, enabled=enabled)

    @server.tool()
    async def dosbox_send_keys(keys: list[str]) -> dict[str, object]:
        """Tap one simultaneous chord of DOSBox-X QKeyCode names."""

        return await asyncio.to_thread(send_keys, qmp, keys)

    @server.tool()
    async def dosbox_key_event(key: str, down: bool) -> dict[str, object]:
        """Press or release one DOSBox-X QKeyCode key."""

        return await asyncio.to_thread(key_event, qmp, key, down=down)

    @server.tool()
    async def dosbox_type_text(
        text: str, press_enter: bool = False
    ) -> dict[str, object]:
        """Type paced US-ASCII text while the guest actively consumes input."""

        return await asyncio.to_thread(
            type_text, qmp, text, press_enter=press_enter
        )

    @server.tool()
    async def dosbox_read_memory(
        address: int,
        size: int,
        output_path: str | None = None,
        overwrite: bool = False,
        allow_running: bool = False,
    ) -> dict[str, object]:
        """Read physical memory; unmapped bytes are indistinguishable from zero."""

        return await asyncio.to_thread(
            read_memory,
            qmp,
            address,
            size,
            output_path=output_path,
            overwrite=overwrite,
            allow_running=allow_running,
        )

    @server.tool()
    async def dosbox_capture_screen() -> Image:
        """Capture the current DOSBox-X display as an MCP PNG image."""

        data = await asyncio.to_thread(capture_screen, qmp)
        return Image(data=data, format="png")

    @server.tool()
    async def dosbox_save_state(
        path: str, overwrite: bool = False
    ) -> dict[str, object]:
        """Save emulator state to an absolute host path."""

        return await asyncio.to_thread(save_state, qmp, path, overwrite=overwrite)

    @server.tool()
    async def dosbox_load_state(path: str) -> dict[str, object]:
        """Load emulator state from an existing absolute host path."""

        return await asyncio.to_thread(load_state, qmp, path)

    return server
