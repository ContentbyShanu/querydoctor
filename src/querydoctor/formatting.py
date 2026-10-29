"""Human-friendly number formatting shared by the CLI, reports and explanations."""

from __future__ import annotations


def fmt_ms(value: float) -> str:
    """Format milliseconds with a sensible precision (``0.42 ms``, ``38 ms``, ``1,204 ms``)."""
    if value >= 100:
        return f"{value:,.0f} ms"
    if value >= 10:
        return f"{value:.0f} ms"
    if value >= 1:
        return f"{value:.1f} ms"
    return f"{value:.2f} ms"


def fmt_speedup(value: float) -> str:
    """Format a speedup factor (``3.4x``, ``197x``, ``1,240x``)."""
    if value >= 10:
        return f"{value:,.0f}x"
    return f"{value:.1f}x"


def fmt_bytes(value: int | float) -> str:
    """Format a byte count (``812 KB``, ``6.2 MB``)."""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"  # pragma: no cover


def fmt_percent(fraction: float) -> str:
    """Format a ratio as a whole percent (``0.376`` becomes ``38%``)."""
    return f"{fraction * 100:.0f}%"
