from __future__ import annotations

import pytest

from querydoctor.formatting import fmt_bytes, fmt_ms, fmt_percent, fmt_speedup


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.42, "0.42 ms"), (3.14, "3.1 ms"), (38.2, "38 ms"), (1204.4, "1,204 ms")],
)
def test_fmt_ms(value: float, expected: str) -> None:
    assert fmt_ms(value) == expected


@pytest.mark.parametrize(("value", "expected"), [(3.44, "3.4x"), (197.2, "197x"), (1240, "1,240x")])
def test_fmt_speedup(value: float, expected: str) -> None:
    assert fmt_speedup(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(512, "512 B"), (2048, "2 KB"), (6 * 1024 * 1024, "6.0 MB"), (3 * 1024**3, "3.0 GB")],
)
def test_fmt_bytes(value: int, expected: str) -> None:
    assert fmt_bytes(value) == expected


def test_fmt_percent() -> None:
    assert fmt_percent(0.376) == "38%"
