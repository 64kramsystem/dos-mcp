"""Caller-visible error categories."""

from __future__ import annotations


class DosMcpError(RuntimeError):
    """Base class for expected DOS MCP failures."""


class QmpTransportError(DosMcpError):
    """The local QMP server could not complete a request."""


class QmpProtocolError(DosMcpError):
    """The peer did not speak the expected bounded QMP subset."""


class QmpCommandError(DosMcpError):
    """DOSBox-X rejected a QMP command."""

    def __init__(self, error_class: str, description: str) -> None:
        super().__init__(f"{error_class}: {description}")
        self.error_class = error_class
        self.description = description


class RequestError(DosMcpError, ValueError):
    """A tool request is invalid or exceeds a safety bound."""

