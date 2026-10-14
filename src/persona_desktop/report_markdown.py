"""Safe, static rendering of the Markdown supported by the product editor."""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\n]*)$")
_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_ORDERED = re.compile(r"^(\s*)(\d+)\.\s+(.+)$")
_INLINE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|(?<!!)\[(?P<label>[^\]]+)\]\((?P<url>[^\s)]+)\)"
    r"|\*\*(?P<strong_star>[^*]+)\*\*|__(?P<strong_under>[^_]+)__"
    r"|\*(?P<em_star>[^*\n]+)\*|_(?P<em_under>[^_\n]+)_"
)


def _safe_link(url: str) -> bool:
    if any(ord(char) <= 32 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def _inline(text: str, depth: int = 0) -> str:
    if depth > 8:
        return html.escape(text)
    parts = []
    cursor = 0
    for match in _INLINE.finditer(text):
        parts.append(html.escape(text[cursor:match.start()]))
        if match.group("code") is not None:
            parts.append("<code>" + html.escape(match.group("code")) + "</code>")
        elif match.group("url") is not None:
            url = match.group("url")
            if _safe_link(url):
                parts.append('<a href="' + html.escape(url, quote=True)
                             + '" rel="noreferrer noopener">'
                             + _inline(match.group("label"), depth + 1) + "</a>")
            else:
                parts.append(html.escape(match.group()))
        else:
            strong = match.group("strong_star") or match.group("strong_under")
            tag = "strong" if strong is not None else "em"
            value = strong if strong is not None else match.group("em_star") or match.group("em_under")
            parts.append(f"<{tag}>" + _inline(value, depth + 1) + f"</{tag}>")
        cursor = match.end()
    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def _cells(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith("\\|"):
        value = value[:-1]
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", value)]


def render_markdown(document: str, title: str = "") -> str:
    """Render product text without executing HTML or loading external resources.

    A supplied product title suppresses only the same initial H1 in the document.
    Unsupported Markdown remains escaped text instead of being discarded.
    """
    lines = str(document or "").splitlines()
    if title:
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            heading = _HEADING.match(line)
            if heading and len(heading[1]) == 1 and heading[2].strip() == title.strip():
                lines.pop(index)
            break

    blocks: list[str] = []
    paragraph: list[str] = []
    lists: list[tuple[str, int]] = []
    list_parts: list[str] = []
    fence: tuple[str, int] | None = None
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append("<p>" + _inline("\n".join(paragraph)).replace("\n", "<br>") + "</p>")
            paragraph.clear()

    def close_list() -> None:
        kind, _ = lists.pop()
        list_parts.append("</li></" + kind + ">")

    def flush_list() -> None:
        if lists:
            while lists:
                close_list()
            blocks.append("".join(list_parts))
            list_parts.clear()

    def emit_code() -> None:
        blocks.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
        code_lines.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        if fence is not None:
            closing = _FENCE_CLOSE.match(line)
            if closing and closing[1][0] == fence[0] and len(closing[1]) >= fence[1]:
                emit_code()
                fence = None
            else:
                code_lines.append(line)
            index += 1
            continue

        opening = _FENCE.match(line)
        if opening and not (opening[1][0] == "`" and "`" in opening[2]):
            flush_paragraph()
            flush_list()
            fence = (opening[1][0], len(opening[1]))
            index += 1
            continue

        if "|" in line and index + 1 < len(lines):
            headings = _cells(line)
            separator = _cells(lines[index + 1])
            if len(headings) == len(separator) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
                flush_paragraph()
                flush_list()
                alignments = ["center" if cell.startswith(":") and cell.endswith(":")
                              else "right" if cell.endswith(":")
                              else "left" if cell.startswith(":") else "" for cell in separator]

                def cell_html(tag: str, value: str, column: int) -> str:
                    alignment = alignments[column]
                    attr = f' class="md-{alignment}"' if alignment else ""
                    return f"<{tag}{attr}>" + _inline(value) + f"</{tag}>"

                header = "".join(cell_html("th", cell, column) for column, cell in enumerate(headings))
                rows = []
                index += 2
                while index < len(lines) and "|" in lines[index] and lines[index].strip():
                    values = _cells(lines[index])
                    # Keep extra values visible; unknown table content must not disappear.
                    if len(values) > len(headings):
                        values[len(headings) - 1:] = [" | ".join(values[len(headings) - 1:])]
                    row = "".join(cell_html("td", values[column] if column < len(values) else "", column)
                                  for column in range(len(headings)))
                    rows.append("<tr>" + row + "</tr>")
                    index += 1
                blocks.append("<table><thead><tr>" + header + "</tr></thead><tbody>"
                              + "".join(rows) + "</tbody></table>")
                continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            index += 1
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading[1])
            blocks.append(f"<h{level}>" + _inline(heading[2]) + f"</h{level}>")
            index += 1
            continue

        bullet = _BULLET.match(line)
        ordered = _ORDERED.match(line)
        if bullet or ordered:
            flush_paragraph()
            item = bullet or ordered
            kind = "ul" if bullet else "ol"
            indent = len(item[1].replace("\t", "    "))
            if len(lists) == 1 and lists[0][1] == indent and lists[0][0] != kind:
                flush_list()
            while lists and lists[-1][1] > indent:
                close_list()
            if lists and lists[-1][1] == indent and lists[-1][0] != kind:
                close_list()
            if lists and lists[-1][1] == indent:
                list_parts.append("</li>")
            else:
                # Use a normalized decimal string without Python's integer digit limit.
                start = (ordered[2].lstrip("0") or "0") if ordered else ""
                list_parts.append("<" + kind + (f' start="{start}"' if ordered else "") + ">")
                lists.append((kind, indent))
            list_parts.append("<li>" + _inline(bullet[2] if bullet else ordered[3]))
            index += 1
            continue

        flush_list()
        if re.match(r"^>\s?", line):
            flush_paragraph()
            quote = re.sub(r"^>\s?", "", line)
            blocks.append("<blockquote><p>" + _inline(quote) + "</p></blockquote>")
        elif re.fullmatch(r"\s*(?:---+|\*\*\*+)\s*", line):
            flush_paragraph()
            blocks.append("<hr>")
        else:
            paragraph.append(line)
        index += 1

    if fence is not None:
        emit_code()
    flush_paragraph()
    flush_list()
    return "".join(blocks)
