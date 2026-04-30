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
from urllib.parse import unquote, urljoin
from urllib.request import Request, urlopen


SOURCE_URL = "https://www.etf.bg.ac.rs/sr/fakultet/zaposleni"
PROFILE_PATH_MARKER = "/sr/fakultet/zaposleni/"
SUBJECT_PATH_MARKER = "/sr/fis/karton_predmeta/"
TABLE_DISPLAY_LENGTH_OPTION = 500
OUTPUT_HEADERS = [
    "Титула",
    "Име",
    "Презиме",
    "Звање/Радно место",
    "Орг. јединица",
    "E-mail",
    "Телефон",
    "id_kategorija_poslova",
    "zaposleni_tip",
    "latinica",
    "Predmeti",
]

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / ".NewSkills"
JSON_OUTPUT = OUTPUT_DIR / "Workers.json"
MD_OUTPUT = OUTPUT_DIR / "Workers.md"
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
            "User-Agent": "Mozilla/5.0 (compatible; ETFWorkersScraper/1.0)",
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


def node_classes(node: Node) -> set[str]:
    return set(node.attrs.get("class", "").split())


def class_contains(node: Node, class_name: str) -> bool:
    return class_name in node_classes(node)


def classes_include(node: Node, class_names: Iterable[str]) -> bool:
    classes = node_classes(node)
    return all(class_name in classes for class_name in class_names)


def text_content(node: Node | str) -> str:
    if isinstance(node, str):
        return node
    text_parts = [text_content(child) for child in node.children]
    return re.sub(r"\s+", " ", unescape("".join(text_parts))).strip()


def clean_url(base_url: str, href: str) -> str:
    href = href.strip()
    if not href:
        return ""

    decoded_href = unquote(href)
    if "mailto:" in decoded_href:
        return decoded_href[decoded_href.index("mailto:") :]

    return urljoin(base_url, href)


def links_from_node(node: Node, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for child in walk(node):
        if child.tag != "a":
            continue
        href = child.attrs.get("href", "").strip()
        label = text_content(child)
        url = clean_url(base_url, href)
        if url:
            links.append({"text": label, "url": url})
    return links


def linked_text_content(node: Node | str, base_url: str) -> str:
    if isinstance(node, str):
        return node

    if node.tag == "a":
        href = node.attrs.get("href", "").strip()
        label = text_content(node)
        url = clean_url(base_url, href)
        if url and label:
            return f"[{label}]({url})"
        return label

    text_parts = [linked_text_content(child, base_url) for child in node.children]
    return re.sub(r"\s+", " ", unescape(" ".join(text_parts))).strip()


def first_text_by_tag(root: Node, tag_name: str) -> str:
    for node in walk(root):
        if node.tag == tag_name:
            return text_content(node)
    return ""


def find_workers_table(root: Node) -> Node | None:
    required_classes = {"adresar", "dataTable", "no-footer"}
    for node in walk(root):
        if node.tag == "table" and classes_include(node, required_classes):
            return node
        # The live HTML currently ships the table as `adresar`; DataTables adds
        # `dataTable no-footer` in the rendered browser DOM.
        if node.tag == "table" and class_contains(node, "adresar"):
            return node
    return None


def direct_cell_children(row: Node) -> list[Node]:
    return [
        child
        for child in row.children
        if isinstance(child, Node) and child.tag in {"th", "td"}
    ]


def table_rows(table: Node) -> list[list[Node]]:
    rows: list[list[Node]] = []
    for row in walk(table):
        if row.tag != "tr":
            continue
        cells = direct_cell_children(row)
        if cells:
            rows.append(cells)
    return rows


def profile_url_from_links(links: list[dict[str, str]]) -> str:
    for link in links:
        url = link["url"]
        if PROFILE_PATH_MARKER in url and url.rstrip("/") != SOURCE_URL:
            return url
    return ""


def cell_to_data(cell: Node, base_url: str) -> dict[str, object]:
    return {
        "text": text_content(cell),
        "markdown": linked_text_content(cell, base_url),
        "links": links_from_node(cell, base_url),
    }


def workers_table_to_data(table: Node, base_url: str) -> dict[str, object]:
    rows = table_rows(table)
    if not rows:
        return {"headers": [], "rows": []}

    headers = [text_content(cell) for cell in rows[0]]
    workers: list[dict[str, object]] = []

    for row_index, row_cells in enumerate(rows[1:], start=1):
        normalized_cells = row_cells + [Node("td")] * (len(headers) - len(row_cells))
        cell_data = [cell_to_data(cell, base_url) for cell in normalized_cells[: len(headers)]]
        values = {
            header: str(cell["text"])
            for header, cell in zip(headers, cell_data, strict=False)
        }
        markdown_values = {
            header: str(cell["markdown"])
            for header, cell in zip(headers, cell_data, strict=False)
        }
        links = {
            header: cell["links"]
            for header, cell in zip(headers, cell_data, strict=False)
            if cell["links"]
        }
        all_links = [link for cell in cell_data for link in cell["links"]]

        workers.append(
            {
                "row_index": row_index,
                "profile_url": profile_url_from_links(all_links),
                "values": values,
                "markdown_values": markdown_values,
                "links": links,
            }
        )

    return {"headers": headers, "rows": workers}


def has_page_length_option(root: Node, option_value: int) -> bool:
    expected_value = str(option_value)
    for node in walk(root):
        if node.tag == "option" and node.attrs.get("value") == expected_value:
            return True
    return False


def scrape_workers_directory() -> tuple[dict[str, object], list[str], bool]:
    root = parse_html(fetch_html(SOURCE_URL))
    table = find_workers_table(root)
    if table is None:
        raise RuntimeError("Could not find table with classes: adresar dataTable no-footer")

    workers_table = workers_table_to_data(table, SOURCE_URL)
    page_length_option_found = has_page_length_option(root, TABLE_DISPLAY_LENGTH_OPTION)
    profile_urls: list[str] = []
    seen: set[str] = set()

    for row in workers_table["rows"]:
        profile_url = row.get("profile_url", "")
        if isinstance(profile_url, str) and profile_url and profile_url not in seen:
            seen.add(profile_url)
            profile_urls.append(profile_url)

    return workers_table, profile_urls, page_length_option_found


def subject_links_from_profile(root: Node, base_url: str) -> list[dict[str, str]]:
    subjects: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for node in walk(root):
        if not classes_include(node, {"offset-md-1", "col-md-10"}):
            continue

        for link in links_from_node(node, base_url):
            url = link["url"]
            if SUBJECT_PATH_MARKER not in url or url in seen_urls:
                continue
            seen_urls.add(url)
            subjects.append(link)

    return subjects


def subject_text(subjects: list[dict[str, str]]) -> str:
    return "; ".join(subject["text"] for subject in subjects if subject["text"])


def subject_markdown(subjects: list[dict[str, str]]) -> str:
    values = []
    for subject in subjects:
        label = subject["text"]
        url = subject["url"]
        if label and url:
            values.append(f"[{label}]({url})")
        elif label:
            values.append(label)
    return "; ".join(values)


def scrape_profile_subjects(url: str) -> list[dict[str, str]]:
    root = parse_html(fetch_html(url))
    return subject_links_from_profile(root, url)


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
        "# Workers",
        "",
        f"Generated: {data['generated_at']}",
        "",
        f"Source: {data['source_url']}",
        f"Table display length option: {data['table_display_length_option']}",
        f"Table display length option found: {data['table_display_length_option_found']}",
        "",
        f"Workers: {len(data['workers'])}",
        "",
        markdown_table(data["markdown_rows"]),
    ]

    return "\n".join(lines).rstrip() + "\n"


def build_worker_row(
    directory_row: dict[str, object],
    subjects: list[dict[str, str]],
    error: str = "",
) -> tuple[dict[str, object], list[str]]:
    values = directory_row.get("values", {})
    markdown_values = directory_row.get("markdown_values", {})
    if not isinstance(values, dict):
        values = {}
    if not isinstance(markdown_values, dict):
        markdown_values = {}

    worker: dict[str, object] = {
        header: str(values.get(header, ""))
        for header in OUTPUT_HEADERS
        if header != "Predmeti"
    }
    worker["Predmeti"] = subject_text(subjects)
    worker["profile_url"] = str(directory_row.get("profile_url", ""))
    if error:
        worker["profile_error"] = error

    markdown_row = [
        subject_markdown(subjects) if header == "Predmeti" else str(markdown_values.get(header, ""))
        for header in OUTPUT_HEADERS
    ]
    return worker, markdown_row


def main() -> int:
    try:
        OUTPUT_DIR.mkdir(exist_ok=True)
        workers_table, profile_urls, page_length_option_found = scrape_workers_directory()

        workers = []
        markdown_rows = [OUTPUT_HEADERS]
        total_rows = len(workers_table["rows"])
        for index, directory_row in enumerate(workers_table["rows"], start=1):
            profile_url = str(directory_row.get("profile_url", ""))
            subjects: list[dict[str, str]] = []
            error = ""

            if profile_url:
                print(f"[{index}/{total_rows}] Scraping {profile_url}")
                try:
                    subjects = scrape_profile_subjects(profile_url)
                except (HTTPError, URLError, TimeoutError) as exc:
                    error = str(exc)
                time.sleep(REQUEST_DELAY_SECONDS)

            worker, markdown_row = build_worker_row(directory_row, subjects, error)
            workers.append(worker)
            markdown_rows.append(markdown_row)

        if len(profile_urls) > TABLE_DISPLAY_LENGTH_OPTION:
            raise RuntimeError(
                "The workers table contains more rows than the configured "
                f"{TABLE_DISPLAY_LENGTH_OPTION} display length."
            )

        if not page_length_option_found:
            print(
                f"Warning: could not find option value={TABLE_DISPLAY_LENGTH_OPTION}; "
                "parsed all rows present in the HTML table.",
                file=sys.stderr,
            )

        data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_url": SOURCE_URL,
            "table_display_length_option": TABLE_DISPLAY_LENGTH_OPTION,
            "table_display_length_option_found": page_length_option_found,
            "headers": OUTPUT_HEADERS,
            "workers": workers,
            "markdown_rows": markdown_rows,
        }

        JSON_OUTPUT.write_text(
            json.dumps(
                {key: value for key, value in data.items() if key != "markdown_rows"},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        MD_OUTPUT.write_text(build_markdown(data), encoding="utf-8")

        errors = sum(1 for worker in workers if "profile_error" in worker)
        workers_with_subjects = sum(1 for worker in workers if worker.get("Predmeti"))

        print(f"Saved JSON: {JSON_OUTPUT}")
        print(f"Saved Markdown: {MD_OUTPUT}")
        print(f"Discovered profiles: {len(profile_urls)}")
        print(f"Saved workers: {len(workers)}")
        print(f"Workers with Predmeti: {workers_with_subjects}")
        print(f"Profile errors: {errors}")
        return 0
    except Exception as exc:
        print(f"Scrape failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
