"""Standalone HTML report (spec §49.14).

A deliberately small markdown converter — headers, tables, lists, block
quotes, code, bold, links, and images — so the harness stays free of a
markdown dependency. Styling is one embedded CSS block; chart images are
referenced relative to the run directory exactly as in ``report.md``.
"""

from __future__ import annotations

import html as html_escape
import re
from pathlib import Path

_STYLE = """
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
       max-width: 1080px; margin: 2rem auto; padding: 0 1rem; color: #1c2733;
       line-height: 1.5; }
h1, h2, h3 { line-height: 1.25; }
h2 { border-bottom: 1px solid #d7dde3; padding-bottom: 0.3rem; margin-top: 2.2rem; }
table { border-collapse: collapse; margin: 1rem 0; font-size: 0.85rem; display: block;
        overflow-x: auto; }
th, td { border: 1px solid #c7ced4; padding: 0.35rem 0.6rem; text-align: left; }
th { background: #eef2f5; }
tr:nth-child(even) td { background: #f7f9fa; }
blockquote { border-left: 4px solid #b0413e; background: #faf1f0; margin: 1rem 0;
             padding: 0.6rem 1rem; }
code { background: #eef2f5; padding: 0.1rem 0.3rem; border-radius: 3px;
       font-size: 0.85em; }
pre code { display: block; padding: 0.8rem; overflow-x: auto; }
img { max-width: 100%; border: 1px solid #d7dde3; margin: 0.5rem 0; }
"""


def _slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return text.strip("-")


def _inline(text: str) -> str:
    text = html_escape.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped.startswith("|")
                and re.fullmatch(r"\|(?:\s*:?-+:?\s*\|)+", stripped))


_ORDERED = re.compile(r"^(\d+)\.\s+(.*)$")


def markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("```"):
            block = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            out.append("<pre><code>" + html_escape.escape("\n".join(block)) + "</code></pre>")
            continue
        header = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if header:
            level = len(header.group(1))
            title = header.group(2)
            out.append(f'<h{level} id="{_slug(title)}">{_inline(title)}</h{level}>')
            index += 1
            continue
        if stripped.startswith("<"):
            out.append(stripped)
            index += 1
            continue
        if stripped.startswith(">"):
            quote = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip().lstrip(">").strip())
                index += 1
            out.append("<blockquote><p>" + _inline(" ".join(quote)) + "</p></blockquote>")
            continue
        if stripped.startswith("|"):
            table = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table.append(lines[index])
                index += 1
            out.append("<table>")
            body_started = False
            for row_index, row in enumerate(table):
                if _is_separator_row(row):
                    body_started = True
                    continue
                tag = "td" if body_started or row_index > 0 else "th"
                cells = "".join(f"<{tag}>{_inline(cell)}</{tag}>" for cell in _table_cells(row))
                out.append(f"<tr>{cells}</tr>")
            out.append("</table>")
            continue
        if stripped.startswith("- "):
            out.append("<ul>")
            while index < len(lines) and lines[index].strip().startswith("- "):
                out.append("<li>" + _inline(lines[index].strip()[2:]) + "</li>")
                index += 1
            out.append("</ul>")
            continue
        ordered = _ORDERED.match(stripped)
        if ordered:
            out.append("<ol>")
            while index < len(lines):
                current = lines[index].strip()
                match = _ORDERED.match(current)
                if match:
                    out.append(f'<li value="{match.group(1)}">{_inline(match.group(2))}</li>')
                    index += 1
                    continue
                if not current:
                    lookahead = index + 1
                    if lookahead < len(lines) and _ORDERED.match(lines[lookahead].strip()):
                        index += 1
                        continue
                break
            out.append("</ol>")
            continue
        paragraph = []
        while index < len(lines) and lines[index].strip() and not re.match(
            r"^(#{1,6}\s|\||>|- |\d+\.\s|```|<)", lines[index].strip()
        ):
            paragraph.append(lines[index].strip())
            index += 1
        out.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
    return "\n".join(out)


def render_html(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    markdown_path = run_dir / "report.md"
    if not markdown_path.exists():
        raise FileNotFoundError(
            f"{markdown_path} does not exist; render the markdown report first"
        )
    markdown = markdown_path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.*)$", markdown, re.MULTILINE)
    title = html_escape.escape(title_match.group(1)) if title_match else "Lexical stability report"
    body = markdown_to_html(markdown)
    document = (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{title}</title>\n<style>{_STYLE}</style>\n</head>\n<body>\n"
        f"{body}\n</body>\n</html>\n"
    )
    html_path = run_dir / "report.html"
    html_path.write_text(document, encoding="utf-8")
    return html_path
