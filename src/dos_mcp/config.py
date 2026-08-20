"""Validated environment-backed settings."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    qmp_port: int
    qmp_timeout: float

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> Settings:
        port_text = environ.get("DOSBOX_X_QMP_PORT", "4444")
        try:
            port = int(port_text, 10)
        except ValueError as error:
            raise ValueError("DOSBOX_X_QMP_PORT must be an integer") from error
        if not 1 <= port <= 65535:
            raise ValueError("DOSBOX_X_QMP_PORT must be between 1 and 65535")

        timeout_text = environ.get("DOSBOX_X_QMP_TIMEOUT", "35")
        try:
            timeout = float(timeout_text)
        except ValueError as error:
            raise ValueError(
                "DOSBOX_X_QMP_TIMEOUT must be a finite positive number"
            ) from error
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(
                "DOSBOX_X_QMP_TIMEOUT must be a finite positive number"
            )
        return cls(qmp_port=port, qmp_timeout=timeout)

