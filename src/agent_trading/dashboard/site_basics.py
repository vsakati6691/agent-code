"""Small static assets and GitHub Pages fallback content."""

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-labelledby="title">
<title id="title">Tikasa Stock Research: T / S</title>
<rect width="64" height="64" rx="12" fill="#152c40"/>
<text x="32" y="40" text-anchor="middle" font-family="Arial,sans-serif" font-size="22" font-weight="700" fill="#ffffff">T/S</text>
</svg>
"""

NOT_FOUND = """<h1>Page not found</h1>
<p>This address does not match a published research page. A bookmark may point to an older route.</p>
<p><a href="index.html">Return to the research overview</a> or
<a href="history.html">browse stored research reports</a>.</p>"""

# GitHub Pages serves this HTML for unknown nested paths as well as root paths.
PAGES_BASE = "https://vsakati6691.github.io/agent-code/"
