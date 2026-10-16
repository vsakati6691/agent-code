"""Offline CI build and internal-file link checks; never reads production data."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class References(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.urls.extend(value for key, value in attrs if key in {"href", "src"} and value)


def check_links(site: Path) -> list[str]:
    """Check local href/src files, including queries and encoded paths.

    Fragments can encode browser filter state rather than element IDs, so they
    are intentionally left to the page-specific interaction tests.
    """
    site = site.resolve()
    pages = sorted(site.rglob("*.html"))
    if not pages:
        return ["No HTML pages were built"]
    problems = []
    for page in pages:
        parser = References()
        parser.feed(page.read_text(encoding="utf-8"))
        for url in parser.urls:
            parts = urlsplit(url)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            path = unquote(parts.path)
            target = ((site / path.lstrip("/")) if path.startswith("/") else page.parent / path).resolve()
            if not target.is_relative_to(site):
                problems.append(f"{page.relative_to(site)}: link escapes the site: {url}")
                continue
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                problems.append(f"{page.relative_to(site)}: missing {url}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--root", type=Path, required=True)
    check = commands.add_parser("check")
    check.add_argument("--site", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        from tests.dashboard_fixtures import demo_site

        data, site = demo_site(args.root)
        print(f"Built synthetic fixture data at {data} and site at {site}")
        return 0
    problems = check_links(args.site)
    for problem in problems:
        print(problem)
    print(f"Checked {len(list(args.site.rglob('*.html')))} HTML pages; {len(problems)} broken links")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
