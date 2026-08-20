from __future__ import annotations

import pytest

from dos_mcp.config import Settings


def test_defaults() -> None:
    assert Settings.from_environ({}) == Settings(qmp_port=4444, qmp_timeout=35.0)


@pytest.mark.parametrize("value", ["0", "65536", "x"])
def test_invalid_port(value: str) -> None:
    with pytest.raises(ValueError, match="DOSBOX_X_QMP_PORT"):
        Settings.from_environ({"DOSBOX_X_QMP_PORT": value})


@pytest.mark.parametrize("value", ["0", "nan", "inf", "x"])
def test_invalid_timeout(value: str) -> None:
    with pytest.raises(ValueError, match="DOSBOX_X_QMP_TIMEOUT"):
        Settings.from_environ({"DOSBOX_X_QMP_TIMEOUT": value})

