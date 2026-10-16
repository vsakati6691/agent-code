"""Compact server-rendered notices; preserve reasons without filling the viewport."""

from html import escape


def notice(title: str, message: str, reasons: list[str] | None = None) -> str:
    detail = ""
    if reasons:
        items = "".join(f"<li>{escape(reason)}</li>" for reason in reasons)
        detail = f"<details><summary>Data availability details ({len(reasons)})</summary><ul>{items}</ul></details>"
    return (
        f'<div class="banner warn data-notice" role="note" aria-label="{escape(title)}">'
        f"<strong>{escape(title)}</strong>{escape(message)}{detail}</div>"
    )
