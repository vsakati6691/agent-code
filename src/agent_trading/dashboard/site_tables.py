"""Accessible scroll regions and stable sort controls for generated table markup."""

import html
import re


def enhance(markup: str) -> str:
    """Enhance only the site's known table wrappers; keep table data and order intact."""

    def missing_cell(match: re.Match) -> str:
        attributes, value = match.groups()
        reason = html.escape(html.unescape(value.strip()), quote=True)
        return f'<td{attributes}><span title="{reason}">—</span></td>'

    markup = re.sub(
        r"<td\b([^>]*)>\s*(n/a|Unavailable|unavailable|not enough history|not meaningful(?: \(negative base\))?)\s*</td>",
        missing_cell,
        markup,
    )

    def region(match: re.Match) -> str:
        classes, table, attributes, caption = match.groups()
        label = re.search(r'\baria-label=[\'"]([^\'"]*)[\'"]', attributes)
        name = label[1] if label else re.sub(r"<[^>]+>", "", caption or "")
        name = html.escape(html.unescape(name or "Research data table"))
        return (
            f'<div class="{classes}" tabindex="0" role="region" aria-label="{name}; scroll for more">'
            f"{table}{caption or ''}"
        )

    markup = re.sub(
        r'<div class="(table-wrap(?: [\w-]+)*)">(<table\b([^>]*)>)(<caption\b[^>]*>.*?</caption>)?',
        region,
        markup,
        flags=re.S,
    )

    def sort_button(match: re.Match) -> str:
        attributes, content = match.groups()
        if "<button" in content:
            return match[0]
        return f'<th{attributes} aria-sort="none"><button type="button" class="sortbtn">{content}</button></th>'

    return re.sub(r"<th\b([^>]*\bdata-sort=[^>]*)>(.*?)</th>", sort_button, markup, flags=re.S)
