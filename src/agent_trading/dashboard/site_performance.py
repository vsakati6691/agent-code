"""Separate browser data from HTML and enforce the public page byte budget."""

import hashlib
import json
import re
from pathlib import Path

HTML_BUDGET = 150_000


def external_json(markup: str, page: str, files: dict[str, str]) -> str:
    """Move known browser-only payloads to same-origin JSON; preserve their exact data."""

    def replace(match):
        key, raw = match.groups()
        path = f"data/{page}-{key}.json"
        files[path] = json.dumps(json.loads(raw), separators=(",", ":"))
        return f'<script type="application/json" id="{key}" data-src="{path}"></script>'

    markup = re.sub(
        r'<script type="application/json" id="(decision-data|cmp-data)">(.*?)</script>', replace, markup, flags=re.S
    )

    def spark(match):
        svg = match.group(0)
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', svg.split(">", 1)[0]))
        path = f"assets/spark-{hashlib.sha256(svg.encode()).hexdigest()[:16]}.svg"
        svg = svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
        svg = svg.replace("var(--series-1)", "var(--series-1, #2a78d6)").replace(
            "var(--reference)", "var(--reference, #686762)"
        )
        style = "<style>@media(prefers-color-scheme:dark){:root{--series-1:#3987e5;--reference:#a3a29b}}</style>"
        files[path] = svg.replace(">", ">" + style, 1)
        return f'<img class="spark" src="{path}" width="{attrs["width"]}" height="{attrs["height"]}" alt="{attrs["aria-label"]}" loading="lazy">'

    return re.sub(r'<svg class="spark"[^>]*>.*?</svg>', spark, markup, flags=re.S)


def budget_problems(out: Path) -> list[str]:
    return [
        f"{p.relative_to(out)}: {p.stat().st_size:,} bytes exceeds the {HTML_BUDGET:,}-byte HTML budget"
        for p in sorted(out.rglob("*.html"))
        if p.stat().st_size > HTML_BUDGET
    ]
