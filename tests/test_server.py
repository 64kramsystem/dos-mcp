import asyncio
import base64
from contextlib import nullcontext
from typing import cast

from mcp import Client

from dos_mcp.config import Settings
from dos_mcp.errors import QmpTransportError
from dos_mcp.qmp import QmpClient
from dos_mcp.server import create_server


def test_current_protocol_lists_tools_and_returns_status_and_image():
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8A"
        "AwMCAO+aX1sAAAAASUVORK5CYII="
    )
    calls = []

    class FakeQmp:
        def session(self):
            return nullcontext(self)

        def execute(self, command, arguments=None):
            calls.append(command)
            if command == "query-status":
                return {"running": True, "emulator-paused": False}
            assert command == "screendump"
            return {"data": base64.b64encode(png).decode()}

    server = create_server(Settings.from_environ({}), cast(QmpClient, FakeQmp()))

    async def run():
        async with Client(server, mode="2026-07-28") as client:
            listing = await client.list_tools()
            assert len(listing.tools) == 13
            assert "dosbox_capture_screen" in {tool.name for tool in listing.tools}
            status = await client.call_tool("dosbox_status", {})
            assert not status.is_error
            assert status.structured_content["running"] is True
            image = await client.call_tool("dosbox_capture_screen", {})
            assert not image.is_error
            assert len(image.content) == 1
            assert image.content[0].mime_type == "image/png"
            assert base64.b64decode(image.content[0].data) == png

    asyncio.run(run())
    assert calls == ["query-status", "query-status", "screendump"]


def test_current_protocol_explains_invalid_input_and_backend_failure():
    class UnavailableQmp:
        def execute(self, command, arguments=None):
            raise QmpTransportError("DOSBox-X connection refused")

    server = create_server(
        Settings.from_environ({}), cast(QmpClient, UnavailableQmp())
    )

    async def run():
        async with Client(server, mode="2026-07-28") as client:
            invalid = await client.call_tool(
                "dosbox_read_memory", {"address": 0, "size": 65537}
            )
            assert invalid.is_error
            assert "size" in invalid.content[0].text
            assert "65536" in invalid.content[0].text

            unavailable = await client.call_tool("dosbox_status", {})
            assert unavailable.is_error
            assert "DOSBox-X connection refused" in unavailable.content[0].text

    asyncio.run(run())
