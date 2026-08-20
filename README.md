# dos-mcp

Small MCP tools for a loopback-only DOSBox-X QMP server. Ghidra's maintained
GDB TraceRMI agent owns debugger state; this server supplies emulator control,
paced keyboard input, bounded memory reads, screenshots, and snapshots.

## Tools

- `dosbox_status`, `dosbox_pause`, `dosbox_resume`, and `dosbox_reset`
- `dosbox_send_keys`, `dosbox_key_event`, and `dosbox_type_text`
- `dosbox_break_on_next_exec`
- `dosbox_read_memory` and `dosbox_capture_screen`
- `dosbox_save_state` and `dosbox_load_state`

Inline memory responses are capped at 4 KiB and returned as hex. Reads up to
64 KiB can instead be written to an absolute `output_path`. Typed text is paced
and capped at 128 US-ASCII characters; it is convenient shell input, not a
cycle-deterministic keyboard primitive. Use `dosbox_key_event` to hold and
release keys. The guest must actively consume its BIOS keyboard ring while text
is sent; a busy program can silently lose input. State paths must be absolute
ASCII paths, and saves do not replace an existing file unless `overwrite=true`.

Input, reset, state, and capture operations require running execution. QMP
memory reads default to requiring a paused emulator because a running read can
be torn; `allow_running=true` opts into that explicitly. QMP pause can be
resumed through `dosbox_resume`; a GDB stop must be continued through GDB.
DOSBox-X zero-fills unreadable physical addresses, so an unmapped byte cannot be
distinguished from a real zero through this QMP interface.

Each tool call opens one local QMP session, completes the QMP handshake, performs
its commands serially, and disconnects. Requests are never retried: a timed-out
mutation may already have happened, so inspect emulator state before repeating
it.

This server requires the companion DOSBox-X build made with
`--enable-remotedebug` and configured with `[dosbox] qmpserver=true`. DOSBox-X
accepts one QMP client at a time; do not attach another monitor while using this
MCP server.

## Configuration

The server uses `127.0.0.1` and never accepts a remote QMP host.

- `DOSBOX_X_QMP_PORT` defaults to `4444`.
- `DOSBOX_X_QMP_TIMEOUT` defaults to `35` seconds.

Run with:

```sh
uv run dos-mcp
```

Apache-2.0.
