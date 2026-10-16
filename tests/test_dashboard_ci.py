from tests.dashboard_ci import check_links


def test_check_links_handles_queries_fragments_assets_and_encoding(tmp_path):
    (tmp_path / "index.html").write_text(
        "<a href='detail.html?view=base#ticker'>Detail</a><img src='chart%20one.svg'>"
        "<a href='https://example.test/missing'>External</a><a href='#put-6m'>State</a>"
        "<a href='mailto:test@example.test'>Contact</a>",
        encoding="utf-8",
    )
    (tmp_path / "detail.html").write_text('<a href="/index.html">Home</a>', encoding="utf-8")
    (tmp_path / "chart one.svg").write_text("<svg/>", encoding="utf-8")
    assert check_links(tmp_path) == []


def test_check_links_rejects_missing_files_and_escapes(tmp_path):
    (tmp_path / "index.html").write_text(
        '<a href="missing.html">Missing</a><script src="../outside.js"></script>', encoding="utf-8"
    )
    problems = check_links(tmp_path)
    assert len(problems) == 2
    assert "missing missing.html" in problems[0]
    assert "escapes the site" in problems[1]


def test_check_links_rejects_empty_build(tmp_path):
    assert check_links(tmp_path) == ["No HTML pages were built"]
