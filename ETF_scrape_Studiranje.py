from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


SEED_URLS = [
    "https://www.etf.bg.ac.rs/sr/studiranje/osnovne-akademske-studije/er/2013",
    "https://www.etf.bg.ac.rs/sr/studiranje/osnovne-akademske-studije/er/2019",
    "https://www.etf.bg.ac.rs/sr/studiranje/osnovne-akademske-studije/softversko-inzenjerstvo-si",
    "https://www.etf.bg.ac.rs/sr/studiranje/master-akademske-studije/elektrotehnika-i-racunarstvo-2013",
    "https://www.etf.bg.ac.rs/sr/studiranje/master-akademske-studije/elektrotehnika-i-racunarstvo-2019",
]

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / ".NewSkills"
JSON_OUTPUT = OUTPUT_DIR / "Studiranje.json"
MD_OUTPUT = OUTPUT_DIR / "Studiranje.md"
REQUEST_DELAY_SECONDS = 0.25


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)


class TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.root = Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        self.stack[-1].children.append(node)

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)

    def handle_entityref(self, name: str) -> None:
        self.stack[-1].children.append(unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.stack[-1].children.append(unescape(f"&#{name};"))


def fetch_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ETFStudyScraper/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=30) as response:
        content_type = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(content_type, errors="replace")


def parse_html(html: str) -> Node:
    parser = TreeBuilder()
    parser.feed(html)
    parser.close()
    return parser.root


def walk(node: Node | str) -> Iterable[Node]:
    if isinstance(node, str):
        return
    yield node
    for child in node.children:
        yield from walk(child)


def class_contains(node: Node, class_name: str) -> bool:
    classes = node.attrs.get("class", "").split()
    return class_name in classes


def text_content(node: Node | str) -> str:
    if isinstance(node, str):
        return node
    text_parts = [text_content(child) for child in node.children]
    return re.sub(r"\s+", " ", unescape(" ".join(text_parts))).strip()


def linked_text_content(node: Node | str, base_url: str) -> str:
    if isinstance(node, str):
        return node

    if node.tag == "a":
        href = node.attrs.get("href", "").strip()
        label = text_content(node)
        if href and label:
            return f"[{label}]({urljoin(base_url, href)})"
        return label

    text_parts = [linked_text_content(child, base_url) for child in node.children]
    return re.sub(r"\s+", " ", unescape(" ".join(text_parts))).strip()


def first_text_by_class(root: Node, class_name: str) -> str:
    for node in walk(root):
        if class_contains(node, class_name):
            return text_content(node)
    return ""


def links_from_sidebar(root: Node, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    for sidebar in walk(root):
        if not class_contains(sidebar, "sidebar"):
            continue

        for node in walk(sidebar):
            if node.tag != "a":
                continue
            href = node.attrs.get("href", "").strip()
            if not href or href.startswith(("#", "mailto:", "tel:")):
                continue
            full_url = urljoin(base_url, href)
            if full_url not in seen:
                seen.add(full_url)
                links.append(full_url)

    return links


def table_to_rows(table: Node, base_url: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in walk(table):
        if row.tag != "tr":
            continue
        cells = [
            linked_text_content(cell, base_url)
            for cell in row.children
            if isinstance(cell, Node) and cell.tag in {"th", "td"}
        ]
        if cells:
            rows.append(cells)
    return rows


def tables_from_page(root: Node, base_url: str) -> list[list[list[str]]]:
    return [table_to_rows(node, base_url) for node in walk(root) if node.tag == "table"]


def study_type_from_url(url: str) -> str:
    if "/osnovne-akademske-studije/" in url:
        return "Osnovne akademske studije"
    if "/master-akademske-studije/" in url:
        return "Master akademske studije"
    return ""


def scrape_page(url: str) -> dict[str, object]:
    root = parse_html(fetch_html(url))
    return {
        "url": url,
        "study_type": study_type_from_url(url),
        "sidebar_title": first_text_by_class(root, "sidebar-title"),
        "strana_header": first_text_by_class(root, "strana-header"),
        "tables": tables_from_page(root, url),
    }


def scrape_seed_links(seed_urls: list[str]) -> tuple[list[dict[str, object]], list[str]]:
    seed_results: list[dict[str, object]] = []
    all_links: list[str] = []
    seen: set[str] = set()

    for seed_url in seed_urls:
        root = parse_html(fetch_html(seed_url))
        links = links_from_sidebar(root, seed_url)
        seed_results.append({"url": seed_url, "sidebar_links": links})

        for link in links:
            if link not in seen:
                seen.add(link)
                all_links.append(link)

        time.sleep(REQUEST_DELAY_SECONDS)

    return seed_results, all_links


def markdown_table(rows: list[list[str]]) -> str:
    width = max((len(row) for row in rows), default=0)
    if width == 0:
        return "_No table rows found._"

    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    divider = ["---"] * width
    body = normalized[1:]

    def render_row(row: list[str]) -> str:
        escaped = [cell.replace("|", "\\|") for cell in row]
        return "| " + " | ".join(escaped) + " |"

    lines = [render_row(header), render_row(divider)]
    lines.extend(render_row(row) for row in body)
    return "\n".join(lines)


def build_markdown(data: dict[str, object]) -> str:
    lines = [
        "# Studiranje",
        "",
        f"Generated: {data['generated_at']}",
        "",
        "## Seed Sidebar Links",
        "",
    ]

    for seed in data["seed_pages"]:
        lines.extend([f"### {seed['url']}", ""])
        sidebar_links = seed["sidebar_links"]
        if sidebar_links:
            lines.extend(f"- {link}" for link in sidebar_links)
        else:
            lines.append("_No sidebar links found._")
        lines.append("")

    lines.extend(["## Scraped Pages", ""])

    for page in data["pages"]:
        page_url = page.get("url", "")
        if "error" in page:
            lines.extend(
                [
                    f"### {page_url}",
                    "",
                    f"- URL: {page_url}",
                    f"- Error: {page['error']}",
                    "",
                ]
            )
            continue

        lines.extend(
            [
                f"### {page['strana_header'] or page_url}",
                "",
                f"- URL: {page_url}",
                f"- Study type: {page['study_type']}",
                f"- Sidebar title: {page['sidebar_title']}",
                f"- Strana header: {page['strana_header']}",
                "",
            ]
        )

        tables = page["tables"]
        if not tables:
            lines.extend(["_No tables found._", ""])
            continue

        for index, table in enumerate(tables, start=1):
            lines.extend([f"#### Table {index}", "", markdown_table(table), ""])

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    try:
        OUTPUT_DIR.mkdir(exist_ok=True)
        seed_pages, discovered_links = scrape_seed_links(SEED_URLS)
        pages = []
        for index, url in enumerate(discovered_links, start=1):
            print(f"[{index}/{len(discovered_links)}] Scraping {url}")
            try:
                pages.append(scrape_page(url))
            except (HTTPError, URLError, TimeoutError) as exc:
                pages.append({"url": url, "error": str(exc)})
            time.sleep(REQUEST_DELAY_SECONDS)

        data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seed_urls": SEED_URLS,
            "seed_pages": seed_pages,
            "pages": pages,
        }

        JSON_OUTPUT.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        MD_OUTPUT.write_text(build_markdown(data), encoding="utf-8")

        print(f"Saved JSON: {JSON_OUTPUT}")
        print(f"Saved Markdown: {MD_OUTPUT}")
        print(f"Discovered links: {len(discovered_links)}")
        print(f"Scraped pages: {len(pages)}")
        return 0
    except Exception as exc:
        print(f"Scrape failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
