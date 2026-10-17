"""Ticker search markup; the inline catalog remains usable without the palette."""

from html import escape


def search(symbols: dict[str, str], base: str) -> str:
    if not symbols:
        return ""
    options = "".join(f'<option value="{escape(t)}">{escape(n)}</option>' for t, n in symbols.items())
    links = " · ".join(f'<a href="{escape(base + t)}.html">{escape(t)}</a>' for t in symbols)
    return (
        f'<form class="symsearch" role="search" data-base="{escape(base)}" onsubmit="return false">'
        '<label class="sr-only" for="symq">Find a ticker</label>'
        '<input id="symq" type="search" list="symlist" placeholder="Find a ticker" autocomplete="off" '
        'aria-describedby="symhint">'
        '<span id="symhint" class="sr-only">Choose a ticker from the list to open its page</span>'
        f'<datalist id="symlist">{options}</datalist>'
        '<button class="command-trigger" type="button" hidden aria-haspopup="dialog" '
        'aria-controls="ticker-command" aria-keyshortcuts="Control+k Meta+k">'
        '<span>Find a ticker</span><kbd aria-hidden="true">Ctrl / ⌘ K</kbd></button></form>'
        f"<noscript><details><summary>Browse tickers</summary><p>{links}</p></details></noscript>"
    )


def dialog() -> str:
    return """<dialog id="ticker-command" class="command-dialog" aria-labelledby="command-title" aria-describedby="command-hint">
<div class="command-head"><h2 id="command-title">Jump to a ticker</h2>
<button class="command-close" type="button" aria-label="Close ticker search">Close <kbd aria-hidden="true">Esc</kbd></button></div>
<label class="sr-only" for="command-query">Search tickers and company names</label>
<input id="command-query" type="search" placeholder="Ticker or company name" autocomplete="off" spellcheck="false" maxlength="100"
role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="command-results" aria-describedby="command-hint">
<ul id="command-results" class="command-results" role="listbox" aria-label="Matching tickers"></ul>
<div class="command-footer"><p id="command-hint" role="status" aria-live="polite" aria-atomic="true">Search across all published lists.</p>
<p class="command-help">↑ ↓ to select · Enter to open</p></div></dialog>"""
