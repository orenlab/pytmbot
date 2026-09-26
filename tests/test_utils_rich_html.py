from __future__ import annotations

import pytest

from pytmbot.utils.rich_html import (
    RICH_MESSAGE_MAX_BLOCKS,
    RICH_MESSAGE_MAX_TEXT_LENGTH,
    RICH_TRUNCATION_NOTICE,
    find_rich_html_issues,
    fit_rich_html,
    measure_rich_html,
    rich_html_to_plain_text,
    rich_paragraphs,
    simple_markdown_to_rich_html,
)


def test_measure_rich_html_counts_blocks_text_and_columns() -> None:
    metrics = measure_rich_html(
        "<p><b>Title &amp; more</b></p>"
        "<table bordered striped>"
        '<tr><th>A</th><th colspan="2">B</th></tr>'
        "<tr><td>1</td><td>2</td><td>3</td></tr>"
        "</table>"
        "<ul><li>x</li><li>y</li></ul>"
    )
    # p + table + 2 rows + ul + 2 li
    assert metrics.blocks == 7
    assert metrics.text_length == len("Title & more") + len("AB123xy")
    assert metrics.max_table_columns == 3
    assert metrics.max_depth == 3
    assert metrics.fits is True


def test_fit_rich_html_returns_same_object_when_within_limits() -> None:
    html = "<p>ok</p>"
    assert fit_rich_html(html) is html


def test_fit_rich_html_cuts_tables_at_row_boundary() -> None:
    rows = "".join(f"<tr><td>row {index}</td></tr>" for index in range(700))
    fitted = fit_rich_html(f"<p><b>T</b></p><table>{rows}</table><footer>f</footer>")

    metrics = measure_rich_html(fitted)
    assert metrics.fits
    assert metrics.blocks == RICH_MESSAGE_MAX_BLOCKS
    assert fitted.endswith(f"</table><p><i>{RICH_TRUNCATION_NOTICE}</i></p>")
    assert find_rich_html_issues(fitted) == []


def test_fit_rich_html_truncates_long_preformatted_text() -> None:
    html = "<p><b>Logs</b></p><pre><code>" + "x" * 40_000 + "</code></pre><p>tail</p>"
    fitted = fit_rich_html(html)

    assert measure_rich_html(fitted).text_length <= RICH_MESSAGE_MAX_TEXT_LENGTH
    assert "…</code></pre>" in fitted
    assert "<p>tail</p>" not in fitted
    assert find_rich_html_issues(fitted) == []


@pytest.mark.parametrize(
    ("html", "expected_issue"),
    [
        ("<h9>x</h9>", "unsupported tag <h9>"),
        ("<p>a<br>b</p>", "unsupported tag <br>"),
        ("<p><table></table></p>", "<table> is not allowed inside <p>"),
        ("<table><tr><td><p>x</p></td></tr></table>", "<p> is not allowed inside <td>"),
        ("plain", "bare text outside a block"),
        ("<ul>x<li>y</li></ul>", "bare text inside <ul>"),
        ("<p>line one\nline two</p>", "newline layout outside <pre>"),
        ("<p><b>x</p>", "unexpected </p>"),
        ("<p>x", "unclosed elements: p"),
    ],
)
def test_find_rich_html_issues_reports_problems(html: str, expected_issue: str) -> None:
    issues = find_rich_html_issues(html)
    assert any(expected_issue in issue for issue in issues), issues


def test_find_rich_html_issues_accepts_preformatted_newlines() -> None:
    assert find_rich_html_issues("<pre><code>a\nb</code></pre>") == []


def test_rich_html_to_plain_text_flattens_structure() -> None:
    text = rich_html_to_plain_text(
        "<p><b>Title</b></p>"
        "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2 &amp; 3</td></tr></table>"
        "<ul><li>x</li><li>y</li></ul>"
        "<footer>done</footer>"
    )
    assert text == "Title\nA | B\n1 | 2 & 3\n• x\n• y\ndone"


def test_rich_paragraphs_escapes_and_skips_blank_lines() -> None:
    assert rich_paragraphs("a < b\n\n c ") == "<p>a &lt; b</p><p>c</p>"
    assert rich_paragraphs("note", italic=True) == "<p><i>note</i></p>"
    assert rich_paragraphs("\n  \n") == ""


def test_simple_markdown_to_rich_html_renders_safe_subset() -> None:
    html = simple_markdown_to_rich_html(
        "## Changed\n"
        "- Bumped `pytelegrambotapi` & **docker**\n"
        "* See [docs](https://example.com/a?b=1&c=2)\n"
        "\n"
        "Raw <script>alert(1)</script>\n"
        "---\n"
    )
    assert html == (
        "<p><b>Changed</b></p>"
        "<ul><li>Bumped <code>pytelegrambotapi</code> &amp; <b>docker</b></li>"
        '<li>See <a href="https://example.com/a?b=1&amp;c=2">docs</a></li></ul>'
        "<p>Raw &lt;script&gt;alert(1)&lt;/script&gt;</p>"
    )
    assert find_rich_html_issues(html) == []


def test_simple_markdown_to_rich_html_caps_lines() -> None:
    html = simple_markdown_to_rich_html(
        "\n".join(f"- item {i}" for i in range(10)), max_lines=3
    )
    assert html == (
        "<ul><li>item 0</li><li>item 1</li><li>item 2</li></ul><p><i>…</i></p>"
    )
