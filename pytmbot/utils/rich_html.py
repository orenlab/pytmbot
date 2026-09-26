#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

Helpers for Telegram Rich Messages HTML (Bot API 10.1+).

Rich messages are limited by text length, block count, nesting depth, and
table width rather than by the classic 4096-character message size. These
helpers measure rendered rich HTML, trim it at a structural boundary when it
does not fit, and derive a plain-text fallback for classic delivery.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from typing import Final

RICH_MESSAGE_MAX_TEXT_LENGTH: Final[int] = 32768
RICH_MESSAGE_MAX_BLOCKS: Final[int] = 500
RICH_MESSAGE_MAX_DEPTH: Final[int] = 16
RICH_TABLE_MAX_COLUMNS: Final[int] = 20

RICH_TRUNCATION_NOTICE: Final[str] = "Output truncated to fit Telegram limits."

# Elements Telegram counts as blocks (including list items and table rows).
RICH_BLOCK_TAGS: Final[frozenset[str]] = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "pre",
        "footer",
        "hr",
        "ul",
        "ol",
        "li",
        "blockquote",
        "aside",
        "table",
        "tr",
        "details",
        "figure",
        "img",
        "video",
        "audio",
        "tg-map",
        "tg-collage",
        "tg-slideshow",
        "tg-math-block",
    }
)

# Inline formatting accepted inside paragraphs, list items, and table cells.
RICH_INLINE_TAGS: Final[frozenset[str]] = frozenset(
    {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "ins",
        "s",
        "strike",
        "del",
        "code",
        "mark",
        "sub",
        "sup",
        "tg-spoiler",
        "a",
        "tg-reference",
        "tg-emoji",
        "tg-time",
        "tg-math",
        "cite",
    }
)

# Structural helpers that are neither standalone blocks nor inline formatting.
_RICH_STRUCTURAL_TAGS: Final[frozenset[str]] = frozenset(
    {"th", "td", "caption", "summary", "figcaption"}
)

RICH_ALLOWED_TAGS: Final[frozenset[str]] = (
    RICH_BLOCK_TAGS | RICH_INLINE_TAGS | _RICH_STRUCTURAL_TAGS
)

_VOID_TAGS: Final[frozenset[str]] = frozenset({"hr", "br", "img", "tg-map"})
_TABLE_CELL_TAGS: Final[frozenset[str]] = frozenset({"th", "td"})
_INLINE_ONLY_CONTAINERS: Final[frozenset[str]] = frozenset(
    {"p", "th", "td", "caption", "summary", "footer"}
    | {"h1", "h2", "h3", "h4", "h5", "h6"}
)
_NO_TEXT_CONTAINERS: Final[frozenset[str]] = frozenset({"table", "tr", "ul", "ol"})
# Closing one of these (or any top-level block) leaves the markup well-formed.
_SAFE_CUT_END_TAGS: Final[frozenset[str]] = frozenset({"tr", "li"})
_PLAIN_TEXT_LINE_TAGS: Final[frozenset[str]] = RICH_BLOCK_TAGS | {"caption", "summary"}
_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
_INLINE_WHITESPACE_PATTERN = re.compile(r"[ \t\r\f\v]+")


@dataclass(frozen=True, slots=True)
class RichHtmlMetrics:
    """Size characteristics of rich HTML that Telegram validates."""

    text_length: int
    blocks: int
    max_depth: int
    max_table_columns: int

    @property
    def fits(self) -> bool:
        """Return True when the markup stays within Telegram rich-message limits."""
        return (
            self.text_length <= RICH_MESSAGE_MAX_TEXT_LENGTH
            and self.blocks <= RICH_MESSAGE_MAX_BLOCKS
            and self.max_depth <= RICH_MESSAGE_MAX_DEPTH
            and self.max_table_columns <= RICH_TABLE_MAX_COLUMNS
        )


type _Token = tuple[str, str, str]


class _RichTokenizer(HTMLParser):
    """Split rich HTML into raw tokens that can be re-joined losslessly."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.tokens: list[_Token] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self.tokens.append(("start", tag, self.get_starttag_text() or f"<{tag}>"))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self.tokens.append(("void", tag, self.get_starttag_text() or f"<{tag}/>"))

    def handle_endtag(self, tag: str) -> None:
        self.tokens.append(("end", tag, f"</{tag}>"))

    def handle_data(self, data: str) -> None:
        self.tokens.append(("data", "", data))

    def handle_entityref(self, name: str) -> None:
        self.tokens.append(("entity", "", f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.tokens.append(("entity", "", f"&#{name};"))


def _tokenize(html: str) -> list[_Token]:
    tokenizer = _RichTokenizer()
    tokenizer.feed(html)
    tokenizer.close()
    return tokenizer.tokens


def _cell_span(start_tag_text: str) -> int:
    match = re.search(r'colspan\s*=\s*"?(\d+)', start_tag_text, re.IGNORECASE)
    if match is None:
        return 1
    return max(1, int(match.group(1)))


def measure_rich_html(html: str) -> RichHtmlMetrics:
    """Measure text length, block count, nesting depth, and table width."""
    text_length = 0
    blocks = 0
    depth = 0
    max_depth = 0
    max_columns = 0
    row_columns = 0

    for kind, tag, raw in _tokenize(html):
        if kind == "data":
            if depth:
                text_length += len(raw)
            else:
                text_length += len(raw.strip())
        elif kind == "entity":
            text_length += 1
        elif kind == "void":
            blocks += tag in RICH_BLOCK_TAGS
        elif kind == "start":
            blocks += tag in RICH_BLOCK_TAGS
            if tag in _VOID_TAGS:
                continue
            depth += 1
            max_depth = max(max_depth, depth)
            if tag == "tr":
                row_columns = 0
            elif tag in _TABLE_CELL_TAGS:
                row_columns += _cell_span(raw)
                max_columns = max(max_columns, row_columns)
        elif kind == "end" and tag not in _VOID_TAGS:
            depth = max(0, depth - 1)

    return RichHtmlMetrics(
        text_length=text_length,
        blocks=blocks,
        max_depth=max_depth,
        max_table_columns=max_columns,
    )


def fit_rich_html(html: str) -> str:
    """
    Return rich HTML that fits Telegram limits.

    Markup that already fits is returned unchanged. Oversized markup is cut at
    the last complete top-level block, table row, or list item (or inside a
    long text run), open elements are closed, and a short notice is appended.
    """
    if measure_rich_html(html).fits:
        return html

    notice = f"<p><i>{escape(RICH_TRUNCATION_NOTICE)}</i></p>"
    block_budget = RICH_MESSAGE_MAX_BLOCKS - 1
    text_budget = RICH_MESSAGE_MAX_TEXT_LENGTH - len(RICH_TRUNCATION_NOTICE) - 1

    output: list[str] = []
    stack: list[str] = []
    blocks = 0
    text_length = 0
    safe_point: tuple[int, tuple[str, ...]] = (0, ())

    def _finish(cut_at: int, open_tags: tuple[str, ...]) -> str:
        closing = "".join(f"</{tag}>" for tag in reversed(open_tags))
        return "".join(output[:cut_at]) + closing + notice

    for kind, tag, raw in _tokenize(html):
        if kind in {"data", "entity"}:
            size = 1 if kind == "entity" else len(raw if stack else raw.strip())
            if text_length + size > text_budget:
                remaining = text_budget - text_length
                if kind == "data" and stack and remaining > 0:
                    output.append(raw[:remaining] + "…")
                    return _finish(len(output), tuple(stack))
                return _finish(*safe_point)
            text_length += size
            output.append(raw)
            continue

        if kind in {"start", "void"} and tag in RICH_BLOCK_TAGS:
            if blocks + 1 > block_budget or len(stack) >= RICH_MESSAGE_MAX_DEPTH:
                return _finish(*safe_point)
            blocks += 1

        output.append(raw)
        if kind == "start" and tag not in _VOID_TAGS:
            stack.append(tag)
        elif kind == "end" and tag in stack:
            while stack and stack.pop() != tag:
                pass
            if not stack or tag in _SAFE_CUT_END_TAGS:
                safe_point = (len(output), tuple(stack))

    return "".join(output)


def find_rich_html_issues(html: str) -> list[str]:
    """
    Report structural problems in rich HTML.

    Checks: only tags Telegram documents for rich HTML, balanced elements,
    inline-only content in paragraphs and table cells, no bare text outside
    blocks, no newline-driven layout outside ``<pre>``, and message limits.
    """
    issues: list[str] = []
    stack: list[str] = []

    for kind, tag, raw in _tokenize(html):
        if kind in {"start", "void"}:
            if tag not in RICH_ALLOWED_TAGS:
                issues.append(f"unsupported tag <{tag}>")
            parent = stack[-1] if stack else None
            if parent in _INLINE_ONLY_CONTAINERS and tag not in RICH_INLINE_TAGS:
                issues.append(f"<{tag}> is not allowed inside <{parent}>")
            if kind == "start" and tag not in _VOID_TAGS:
                stack.append(tag)
        elif kind == "end":
            if tag in _VOID_TAGS:
                continue
            if not stack or stack[-1] != tag:
                issues.append(f"unexpected </{tag}>")
                if tag in stack:
                    while stack and stack.pop() != tag:
                        pass
                continue
            stack.pop()
        elif kind == "data" and raw.strip():
            if not stack:
                issues.append(f"bare text outside a block: {raw.strip()[:40]!r}")
            elif stack[-1] in _NO_TEXT_CONTAINERS:
                issues.append(f"bare text inside <{stack[-1]}>: {raw.strip()[:40]!r}")
            elif "pre" not in stack and "\n" in raw.strip():
                issues.append(f"newline layout outside <pre>: {raw.strip()[:40]!r}")

    if stack:
        issues.append(f"unclosed elements: {', '.join(stack)}")

    metrics = measure_rich_html(html)
    if not metrics.fits:
        issues.append(f"exceeds rich message limits: {metrics}")
    return issues


class _PlainTextExtractor(HTMLParser):
    """Flatten rich HTML into readable plain text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._pre_depth = 0
        self._row_has_cell = False

    def _newline(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "pre":
            self._pre_depth += 1
        if tag in _PLAIN_TEXT_LINE_TAGS:
            self._newline()
        if tag == "tr":
            self._row_has_cell = False
        elif tag in _TABLE_CELL_TAGS:
            if self._row_has_cell:
                self.parts.append(" | ")
            self._row_has_cell = True
        elif tag == "li":
            self.parts.append("• ")
        elif tag == "hr":
            self.parts.append("———")
        elif tag == "br":
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
        if tag in _PLAIN_TEXT_LINE_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._pre_depth:
            self.parts.append(data)
            return
        collapsed = _INLINE_WHITESPACE_PATTERN.sub(" ", data.replace("\n", " "))
        if collapsed.strip():
            self.parts.append(collapsed)


def rich_html_to_plain_text(html: str) -> str:
    """Convert rich HTML into plain text for classic message fallbacks."""
    extractor = _PlainTextExtractor()
    extractor.feed(html)
    extractor.close()
    lines = [line.strip() for line in "".join(extractor.parts).splitlines()]
    text = "\n".join(lines)
    return _BLANK_LINES_PATTERN.sub("\n\n", text).strip()


def rich_paragraphs(text: str, *, italic: bool = False) -> str:
    """
    Wrap plain text into escaped rich paragraphs, one ``<p>`` per line.

    Useful for short status or error notices that need to replace rich content.
    """
    paragraphs: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        body = escape(stripped, quote=False)
        paragraphs.append(f"<p><i>{body}</i></p>" if italic else f"<p>{body}</p>")
    return "".join(paragraphs)


_MARKDOWN_HEADING_PATTERN = re.compile(r"^#{1,6}\s+")
_MARKDOWN_BULLET_PATTERN = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_MARKDOWN_CODE_PATTERN = re.compile(r"`([^`]+)`")
_MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _markdown_inline_to_rich_html(text: str) -> str:
    rendered = escape(text, quote=True)
    rendered = _MARKDOWN_LINK_PATTERN.sub(r'<a href="\2">\1</a>', rendered)
    rendered = _MARKDOWN_CODE_PATTERN.sub(r"<code>\1</code>", rendered)
    return _MARKDOWN_BOLD_PATTERN.sub(
        lambda match: f"<b>{match.group(1) or match.group(2)}</b>", rendered
    )


def simple_markdown_to_rich_html(text: str, *, max_lines: int = 40) -> str:
    """
    Render a small, safe subset of Markdown (e.g. release notes) as rich HTML.

    Headings become bold paragraphs, bullet and numbered items become list
    items, and inline code, bold text, and links are preserved. Everything
    else is escaped. Output is capped at ``max_lines`` non-empty lines.
    """
    blocks: list[str] = []
    items: list[str] = []

    def _flush_items() -> None:
        if items:
            blocks.append(
                "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"
            )
            items.clear()

    shown_lines = 0
    truncated = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or set(line) <= {"-", "*", "_", "="}:
            _flush_items()
            continue
        if shown_lines >= max_lines:
            truncated = True
            break
        shown_lines += 1

        if _MARKDOWN_HEADING_PATTERN.match(line):
            _flush_items()
            heading = _MARKDOWN_HEADING_PATTERN.sub("", line)
            blocks.append(f"<p><b>{_markdown_inline_to_rich_html(heading)}</b></p>")
        elif _MARKDOWN_BULLET_PATTERN.match(line):
            item = _MARKDOWN_BULLET_PATTERN.sub("", line)
            items.append(_markdown_inline_to_rich_html(item))
        else:
            _flush_items()
            blocks.append(f"<p>{_markdown_inline_to_rich_html(line)}</p>")

    _flush_items()
    if truncated:
        blocks.append("<p><i>…</i></p>")
    return "".join(blocks)


__all__ = [
    "RICH_ALLOWED_TAGS",
    "RICH_BLOCK_TAGS",
    "RICH_INLINE_TAGS",
    "RICH_MESSAGE_MAX_BLOCKS",
    "RICH_MESSAGE_MAX_DEPTH",
    "RICH_MESSAGE_MAX_TEXT_LENGTH",
    "RICH_TABLE_MAX_COLUMNS",
    "RICH_TRUNCATION_NOTICE",
    "RichHtmlMetrics",
    "find_rich_html_issues",
    "fit_rich_html",
    "measure_rich_html",
    "rich_html_to_plain_text",
    "rich_paragraphs",
    "simple_markdown_to_rich_html",
]
