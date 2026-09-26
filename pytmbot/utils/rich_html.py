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
# Blocks closed directly inside these containers are safe cut points as well.
_SECTION_CONTAINERS: Final[frozenset[str]] = frozenset({"details", "blockquote"})
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

    # codeclone: ignore[dead-code]
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self.tokens.append(("start", tag, self.get_starttag_text() or f"<{tag}>"))

    # codeclone: ignore[dead-code]
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        self.tokens.append(("void", tag, self.get_starttag_text() or f"<{tag}/>"))

    # codeclone: ignore[dead-code]
    def handle_endtag(self, tag: str) -> None:
        self.tokens.append(("end", tag, f"</{tag}>"))

    # codeclone: ignore[dead-code]
    def handle_data(self, data: str) -> None:
        self.tokens.append(("data", "", data))

    # codeclone: ignore[dead-code]
    def handle_entityref(self, name: str) -> None:
        self.tokens.append(("entity", "", f"&{name};"))

    # codeclone: ignore[dead-code]
    def handle_charref(self, name: str) -> None:
        self.tokens.append(("entity", "", f"&#{name};"))


def _tokenize(html: str) -> list[_Token]:
    tokenizer = _RichTokenizer()
    tokenizer.feed(html)
    tokenizer.close()
    return tokenizer.tokens


def _cell_span(start_tag_text: str) -> int:
    match = re.search(r"colspan\s*=\s*[\"']?(\d+)", start_tag_text, re.IGNORECASE)
    if match is None:
        return 1
    return max(1, int(match.group(1)))


def _text_size(text: str) -> int:
    """Count text in UTF-16 code units, the stricter of Telegram's length units."""
    return len(text.encode("utf-16-le")) // 2


def _clip_text(text: str, budget: int) -> str:
    """Return the longest prefix of ``text`` whose size fits ``budget``."""
    size = 0
    for index, char in enumerate(text):
        size += _text_size(char)
        if size > budget:
            return text[:index]
    return text


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
            text_length += _text_size(raw if depth else raw.strip())
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


class _RichFitter:
    """Stream rich HTML tokens and cut them once Telegram limits would be exceeded."""

    def __init__(self) -> None:
        self.output: list[str] = []
        self.stack: list[str] = []
        self.blocks = 0
        self.text_length = 0
        self.row_columns = 0
        self.skip_depth = 0
        self.dropped_cells = False
        self.safe_point: tuple[int, tuple[str, ...]] = (0, ())
        self.block_budget = RICH_MESSAGE_MAX_BLOCKS - 1
        # One extra character is reserved for the ellipsis of a clipped text run.
        self.text_budget = (
            RICH_MESSAGE_MAX_TEXT_LENGTH - _text_size(RICH_TRUNCATION_NOTICE) - 1
        )

    @staticmethod
    def _notice() -> str:
        return f"<p><i>{escape(RICH_TRUNCATION_NOTICE)}</i></p>"

    def finish(self, cut_at: int, open_tags: tuple[str, ...]) -> str:
        closing = "".join(f"</{tag}>" for tag in reversed(open_tags))
        return "".join(self.output[:cut_at]) + closing + self._notice()

    def fit(self, html: str) -> str:
        for kind, tag, raw in _tokenize(html):
            if self.skip_depth:
                self._skip(kind, tag)
                continue
            if kind in {"data", "entity"}:
                result = self._text(kind, raw)
            else:
                result = self._tag(kind, tag, raw)
            if result is not None:
                return result
        fitted = "".join(self.output)
        return fitted + self._notice() if self.dropped_cells else fitted

    def _skip(self, kind: str, tag: str) -> None:
        if kind == "start" and tag not in _VOID_TAGS:
            self.skip_depth += 1
        elif kind == "end" and tag not in _VOID_TAGS:
            self.skip_depth -= 1

    def _text(self, kind: str, raw: str) -> str | None:
        size = 1 if kind == "entity" else _text_size(raw if self.stack else raw.strip())
        if self.text_length + size <= self.text_budget:
            self.text_length += size
            self.output.append(raw)
            return None
        remaining = max(0, self.text_budget - self.text_length)
        if self.stack and self.stack[-1] not in _NO_TEXT_CONTAINERS:
            # Cut inside the text run; an entity is dropped whole, never split.
            clipped = _clip_text(raw, remaining) if kind == "data" else ""
            self.output.append(clipped + "…")
            return self.finish(len(self.output), tuple(self.stack))
        return self.finish(*self.safe_point)

    def _tag(self, kind: str, tag: str, raw: str) -> str | None:
        if kind == "end":
            self._close(tag, raw)
            return None
        if tag in RICH_BLOCK_TAGS:
            if self.blocks + 1 > self.block_budget:
                return self.finish(*self.safe_point)
            self.blocks += 1
        if kind == "start" and tag not in _VOID_TAGS:
            if len(self.stack) >= RICH_MESSAGE_MAX_DEPTH:
                return self.finish(*self.safe_point)
            if not self._open_cell(tag, raw):
                return None
            self.stack.append(tag)
        self.output.append(raw)
        return None

    def _open_cell(self, tag: str, raw: str) -> bool:
        """Track table width; return False when the cell must be dropped."""
        if tag == "tr":
            self.row_columns = 0
        elif tag in _TABLE_CELL_TAGS:
            self.row_columns += _cell_span(raw)
            if self.row_columns > RICH_TABLE_MAX_COLUMNS:
                self.skip_depth = 1
                self.dropped_cells = True
                return False
        return True

    def _close(self, tag: str, raw: str) -> None:
        self.output.append(raw)
        if tag not in self.stack:
            return
        while self.stack.pop() != tag:
            pass
        if (
            not self.stack
            or tag in _SAFE_CUT_END_TAGS
            or (tag in RICH_BLOCK_TAGS and self.stack[-1] in _SECTION_CONTAINERS)
        ):
            self.safe_point = (len(self.output), tuple(self.stack))


def fit_rich_html(html: str) -> str:
    """
    Return rich HTML that fits Telegram limits.

    Markup that already fits is returned unchanged. Oversized markup is cut at
    the last complete top-level block, table row, or list item (or inside a
    long text run), cells beyond the table width limit are dropped, open
    elements are closed, and a short notice is appended.
    """
    if measure_rich_html(html).fits:
        return html
    return _RichFitter().fit(html)


def _open_tag_issues(tag: str, stack: list[str]) -> list[str]:
    issues: list[str] = []
    if tag not in RICH_ALLOWED_TAGS:
        issues.append(f"unsupported tag <{tag}>")
    parent = stack[-1] if stack else None
    if parent in _INLINE_ONLY_CONTAINERS and tag not in RICH_INLINE_TAGS:
        issues.append(f"<{tag}> is not allowed inside <{parent}>")
    return issues


def _close_tag_issues(tag: str, stack: list[str]) -> list[str]:
    if stack and stack[-1] == tag:
        stack.pop()
        return []
    if tag in stack:
        while stack.pop() != tag:
            pass
    return [f"unexpected </{tag}>"]


def _text_issues(text: str, stack: list[str]) -> list[str]:
    snippet = repr(text[:40])
    if not stack:
        return [f"bare text outside a block: {snippet}"]
    if stack[-1] in _NO_TEXT_CONTAINERS:
        return [f"bare text inside <{stack[-1]}>: {snippet}"]
    if "pre" not in stack and "\n" in text:
        return [f"newline layout outside <pre>: {snippet}"]
    return []


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
            issues.extend(_open_tag_issues(tag, stack))
            if kind == "start" and tag not in _VOID_TAGS:
                stack.append(tag)
        elif kind == "end" and tag not in _VOID_TAGS:
            issues.extend(_close_tag_issues(tag, stack))
        elif kind == "data" and raw.strip():
            issues.extend(_text_issues(raw.strip(), stack))

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

    # codeclone: ignore[dead-code]
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

    # codeclone: ignore[dead-code]
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    # codeclone: ignore[dead-code]
    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
        if tag in _PLAIN_TEXT_LINE_TAGS:
            self._newline()

    # codeclone: ignore[dead-code]
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
# Code spans and links are matched first so bold markers never apply inside them.
# Link text and URL lengths are bounded to keep matching linear on odd input.
_MARKDOWN_SPAN_PATTERN = re.compile(
    r"`([^`]+)`|\[([^\]\n]{1,300})\]\((https?://[^)\s]{1,2048})\)"
)
_MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*([^*]+)\*\*|(?<!\w)__([^_]+)__(?!\w)")


def _markdown_plain_to_rich_html(text: str) -> str:
    escaped = escape(text, quote=False)
    return _MARKDOWN_BOLD_PATTERN.sub(
        lambda match: f"<b>{match.group(1) or match.group(2)}</b>", escaped
    )


def _markdown_inline_to_rich_html(text: str) -> str:
    parts: list[str] = []
    position = 0
    for match in _MARKDOWN_SPAN_PATTERN.finditer(text):
        parts.append(_markdown_plain_to_rich_html(text[position : match.start()]))
        code, link_text, url = match.groups()
        if code is not None:
            parts.append(f"<code>{escape(code, quote=False)}</code>")
        else:
            parts.append(
                f'<a href="{escape(url, quote=True)}">{escape(link_text, quote=False)}</a>'
            )
        position = match.end()
    parts.append(_markdown_plain_to_rich_html(text[position:]))
    return "".join(parts)


class _MarkdownBlocks:
    """Collect rich blocks for the Markdown subset used in release notes."""

    def __init__(self) -> None:
        self.blocks: list[str] = []
        self.items: list[str] = []
        self.paragraph: list[str] = []

    def flush(self) -> None:
        if self.paragraph:
            self.blocks.append(f"<p>{' '.join(self.paragraph)}</p>")
            self.paragraph.clear()
        if self.items:
            rendered = "".join(f"<li>{item}</li>" for item in self.items)
            self.blocks.append(f"<ul>{rendered}</ul>")
            self.items.clear()

    def add_line(self, raw_line: str, line: str) -> None:
        if _MARKDOWN_HEADING_PATTERN.match(line):
            self.flush()
            heading = _MARKDOWN_HEADING_PATTERN.sub("", line)
            self.blocks.append(
                f"<p><b>{_markdown_inline_to_rich_html(heading)}</b></p>"
            )
        elif _MARKDOWN_BULLET_PATTERN.match(line):
            if self.paragraph:
                self.flush()
            item = _MARKDOWN_BULLET_PATTERN.sub("", line)
            self.items.append(_markdown_inline_to_rich_html(item))
        elif self.items and raw_line[:1].isspace():
            # Hard-wrapped continuation of the previous bullet.
            self.items[-1] += " " + _markdown_inline_to_rich_html(line)
        else:
            if self.items:
                self.flush()
            self.paragraph.append(_markdown_inline_to_rich_html(line))


def simple_markdown_to_rich_html(text: str, *, max_lines: int = 40) -> str:
    """
    Render a small, safe subset of Markdown (e.g. release notes) as rich HTML.

    Headings become bold paragraphs, bullet and numbered items become list
    items (hard-wrapped continuation lines are joined), consecutive lines form
    one paragraph, and inline code, bold text, and links are preserved.
    Everything else is escaped. Output is capped at ``max_lines`` non-empty
    lines.
    """
    collector = _MarkdownBlocks()
    shown_lines = 0
    truncated = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or set(line) <= {"-", "*", "_", "="}:
            collector.flush()
            continue
        if shown_lines >= max_lines:
            truncated = True
            break
        shown_lines += 1
        collector.add_line(raw_line, line)

    collector.flush()
    if truncated:
        collector.blocks.append("<p><i>…</i></p>")
    return "".join(collector.blocks)


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
