# Changelog

## Unreleased

### Changed

- **Breaking:** pin the MCP Python SDK to 2.3.0 and migrate the stdio server and image responses to `MCPServer`.
- Keep expected request and QMP error details visible to MCP clients.

### Tests

- Cover current-protocol tool listing, status and image responses, invalid requests, and unavailable QMP backends.

## 0.1.3
### Documentation

- Document the Ghidra 12.2 / JDK 25 companion stack and the disposable DOSBox-X TraceRMI integration test.


## 0.1.2
- Document the maintained DOSBox-X remote-debug fork as the emulator dependency.

## 0.1.1
- Add bounded DOSBox-X QMP control, input, capture, memory, and state tools.
- Add host-side floppy image swapping for multi-disk guest workflows.
