"""Explain whether stored ranks actually include the registered sector deduction."""

from .site_layout import E


def status(snap: dict, keys: list[str]) -> str:
    rows = [c for key in keys for c in (snap.get("bands", {}).get(key) or {}).get("candidates", [])]
    if not rows:
        return ""
    if not all(c.get("raw_composite") is not None and "sector_penalty" in c for c in rows):
        return (
            '<div class="banner warn"><strong>Sector adjustment pending a new collection</strong>'
            f"This stored snapshot ({E(str(snap.get('as_of')))}; methodology {E(str(snap.get('spec_version')))}) "
            "predates recorded sector deductions. Rebuilding the site preserves its original ranks. "
            "New collections apply the registered penalty before selecting candidates.</div>"
        )
    penalized = sum(c["sector_penalty"] > 0 for c in rows)
    strengthened = all(
        (snap.get("bands", {}).get(key, {}).get("sector_adjustment") or {}).get("it_multiplier") == 3
        for key in keys
        if snap.get("bands", {}).get(key, {}).get("candidates")
    )
    return (
        '<p class="small"><strong>Sector adjustment applied before selection.</strong> '
        f"{penalized} of {len(rows)} displayed candidates received a deduction. "
        "The soft penalty starts above 50% sector concentration; it cannot guarantee diversity when eligible alternatives are scarce. "
        "Unknown sectors retain their score.</p>"
        + (
            '<p class="small">Information Technology uses a 3× deduction, up to 30 points, above 50% equal-weight list concentration.</p>'
            if strengthened
            else '<p class="small">The stronger 3× Information Technology deduction is pending a new collection; these stored scores retain their original penalty.</p>'
        )
    )
