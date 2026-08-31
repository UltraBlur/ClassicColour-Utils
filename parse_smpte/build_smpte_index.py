#!/usr/bin/env python3
"""Build a searchable index for the SMPTE public document library.

The generated index is based on public SMPTE listing pages. It does not need to
download every PDF; it collects titles, document URLs, version URLs, status
labels, and inferred subject areas from the document titles.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


BASE_URL = "https://pub.smpte.org"
INDEX_URL = f"{BASE_URL}/doc/"
DEFAULT_USER_AGENT = (
    "ClassicColour-Utils SMPTE public index builder "
    "(contact: local research use)"
)
DOC_RE = re.compile(r"^/doc/[^/]+/$")
VERSION_RE = re.compile(r"^/doc/[^/]+/\d{8}[^/]*/$")
DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")
DOCTYPE_RE = re.compile(r"^(ST|RP|EG|RDD|OV|AG|TSP|VC|OV|DG)\s+[\w.-]+", re.I)
FAMILY_RE = re.compile(r"^([A-Z]+)\s+(\d+)", re.I)


CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Color, HDR, imaging, and display",
        (
            "color",
            "colour",
            "hdr",
            "high dynamic range",
            "display",
            "monitor",
            "picture monitor",
            "cie",
            "luminance",
            "chromaticity",
            "brightness",
            "image quality",
            "test signal",
            "test pattern",
            "bars",
            "transfer characteristic",
            "oetf",
            "eotf",
            "optical-electrical",
            "electro-optical",
        ),
    ),
    (
        "Video formats, interfaces, and signal transport",
        (
            "video",
            "television",
            "serial digital",
            "interface",
            "sdi",
            "uhd",
            "4k",
            "8k",
            "raster",
            "sample structure",
            "ancillary data",
            "payload",
            "bitstream",
            "mapping",
            "transport",
            "link",
        ),
    ),
    (
        "Cinema, film, projection, and mastering",
        (
            "motion-picture",
            "motion picture",
            "cinema",
            "d-cinema",
            "digital cinema",
            "projection",
            "projector",
            "film",
            "theatre",
            "theater",
            "dcp",
            "composition playlist",
            "packing list",
            "interoperability",
        ),
    ),
    (
        "Audio",
        (
            "audio",
            "sound",
            "loudness",
            "speaker",
            "microphone",
            "channel",
            "immersive",
            "aes",
        ),
    ),
    (
        "Metadata, captions, subtitles, and identifiers",
        (
            "metadata",
            "identifier",
            "unique material identifier",
            "umid",
            "caption",
            "subtitle",
            "subtitling",
            "closed-caption",
            "closed caption",
            "data dictionary",
            "registry",
            "label",
            "uuid",
            "xml",
            "schema",
        ),
    ),
    (
        "Files, wrappers, and interchange",
        (
            "mxf",
            "material exchange format",
            "file",
            "wrapper",
            "exchange",
            "archive",
            "package",
            "essence",
            "jpeg",
            "mpeg",
            "h.264",
            "hevc",
            "avc",
            "vc-",
            "interchange",
        ),
    ),
    (
        "Timing, synchronization, and control",
        (
            "time code",
            "timecode",
            "time and control",
            "synchronization",
            "synchronisation",
            "sync",
            "genlock",
            "clock",
            "ptp",
            "epoch",
            "time label",
        ),
    ),
    (
        "IP, networking, and remote control",
        (
            "ip",
            "network",
            "ethernet",
            "snmp",
            "mib",
            "remote",
            "control protocol",
            "streaming",
            "rtp",
            "udp",
        ),
    ),
    (
        "Measurement, calibration, and test methods",
        (
            "measurement",
            "calibration",
            "alignment",
            "test",
            "method",
            "reference",
            "signal generator",
            "operating level",
            "frequency response",
        ),
    ),
    (
        "Storage, recording, and physical media",
        (
            "recording",
            "recorder",
            "tape",
            "magnetic",
            "disk",
            "storage",
            "reel",
            "perforation",
            "raw stock",
            "container",
        ),
    ),
]


KEYWORD_RULES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (
        ("interoperable master format", "imf", "st 2067"),
        ("IMF", "Interoperable Master Format", "Mastering", "File interchange"),
    ),
    (
        ("material exchange format", "mxf", "st 377", "st 379"),
        ("MXF", "Material Exchange Format", "Wrapper", "Essence", "File interchange"),
    ),
    (
        ("digital cinema", "d-cinema", "dcp", "composition playlist", "packing list", "rp 431"),
        ("Digital Cinema", "D-Cinema", "DCP", "Cinema package"),
    ),
    (
        ("high dynamic range", "hdr", "pq", "perceptual quantizer", "st 2084"),
        ("HDR", "PQ", "Perceptual Quantizer", "Display"),
    ),
    (
        ("time code", "timecode", "time and control code", "st 12"),
        ("Timecode", "Synchronization", "Timing"),
    ),
    (
        ("metadata", "data dictionary", "registry", "identifier", "umid", "uuid", "label"),
        ("Metadata", "Registry", "Identifier"),
    ),
    (
        ("caption", "closed caption", "closed-caption", "subtitle", "subtitling"),
        ("Captions", "Subtitles", "Accessibility"),
    ),
    (
        ("serial digital", "sdi", "12g", "6g", "3g", "interface", "st 292", "st 424"),
        ("SDI", "Video interface", "Signal transport"),
    ),
    (
        ("ip", "network", "ethernet", "rtp", "ptp", "smpte 2110", "st 2110"),
        ("IP Video", "Networking", "RTP", "PTP"),
    ),
    (
        ("audio", "sound", "loudness", "immersive"),
        ("Audio", "Sound", "Loudness"),
    ),
    (
        ("color", "colour", "display", "monitor", "luminance", "chromaticity", "cie"),
        ("Color", "Display", "Imaging"),
    ),
    (
        ("jpeg", "mpeg", "h.264", "avc", "hevc", "vc-", "compression", "bitstream"),
        ("Compression", "Codec", "Bitstream"),
    ),
    (
        ("ancillary data", "payload", "vanc", "hanc", "mapping"),
        ("Ancillary Data", "Payload", "Mapping"),
    ),
    (
        ("archive", "preservation", "storage", "recording", "tape", "magnetic"),
        ("Archive", "Storage", "Recording"),
    ),
    (
        ("test", "measurement", "calibration", "alignment", "reference signal"),
        ("Measurement", "Calibration", "Test Method"),
    ),
]


TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "IMF": ("imf", "interoperable master format"),
    "MXF": ("mxf", "material exchange format"),
    "HDR": ("hdr", "high dynamic range"),
    "PQ": ("pq", "perceptual quantizer"),
    "SDI": ("sdi", "serial digital interface"),
    "IP Video": ("ip video", "smpte 2110", "st 2110"),
    "DCP": ("dcp", "digital cinema package"),
    "D-Cinema": ("d-cinema", "digital cinema"),
    "PTP": ("ptp", "precision time protocol"),
    "RTP": ("rtp", "real-time transport protocol"),
    "Timecode": ("timecode", "time code"),
    "Metadata": ("metadata", "meta data"),
}


@dataclass
class Link:
    url: str
    text: str
    tag: str
    attrs: dict[str, str]


@dataclass
class Version:
    label: str
    date: str
    url: str
    kind: str


@dataclass
class DocumentRecord:
    designator: str
    title: str
    doc_type: str
    category: str
    family: str
    tags: list[str]
    aliases: list[str]
    search_text: str
    status: str
    doc_url: str
    version_count: int
    latest_date: str
    latest_url: str
    versions: list[Version]
    source: str


class PageParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.links: list[Link] = []
        self.status = ""
        self._current_link: dict[str, object] | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value for name, value in attrs if value is not None}
        if tag.lower() == "span" and attr_map.get("id") == "state":
            self.status = attr_map.get("class", "").replace("state-", "").strip()
        href = attr_map.get("href")
        if href:
            self._current_link = {
                "url": urljoin(self.page_url, html.unescape(href)),
                "tag": tag.lower(),
                "attrs": attr_map,
            }
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._current_link is not None:
            self._link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._current_link is None:
            return
        if tag.lower() != self._current_link["tag"]:
            return
        text = " ".join("".join(self._link_text).split())
        self.links.append(
            Link(
                url=str(self._current_link["url"]),
                text=text,
                tag=str(self._current_link["tag"]),
                attrs=dict(self._current_link["attrs"]),
            )
        )
        self._current_link = None
        self._link_text = []


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build CSV/JSON/HTML index for public SMPTE document pages."
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(Path(__file__).resolve().parent / "index_site"),
        help="Output directory. Default: parse_smpte/index_site",
    )
    parser.add_argument(
        "--index-url",
        default=INDEX_URL,
        help=f"SMPTE index URL. Default: {INDEX_URL}",
    )
    parser.add_argument("--delay", type=float, default=0.15, help="Delay between requests.")
    parser.add_argument("--timeout", type=float, default=60, help="HTTP timeout in seconds.")
    parser.add_argument("--retries", type=int, default=3, help="Retries per request.")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--max-docs", type=int, default=None, help="Limit pages for testing.")
    return parser.parse_args(argv)


def log(message: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_message = message.encode(encoding, errors="replace").decode(encoding)
    print(safe_message, flush=True)


def fetch_text(url: str, user_agent: str, timeout: float, retries: int, delay: float) -> str:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers={"User-Agent": user_agent})
            with urlopen(request, timeout=timeout) as response:
                data = response.read()
            return data.decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(delay * attempt + 0.5)
    raise RuntimeError(f"failed to fetch {url}: {last_error}") from last_error


def normalized_path(url: str) -> str:
    path = urlparse(url).path
    return path if path.startswith("/") else "/" + path


def parse_page(page_url: str, text: str) -> PageParser:
    parser = PageParser(page_url)
    parser.feed(text)
    return parser


def discover_docs(index_url: str, index_html: str) -> list[tuple[str, str]]:
    parser = parse_page(index_url, index_html)
    docs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for link in parser.links:
        path = normalized_path(link.url)
        if DOC_RE.match(path) and path != "/doc/" and link.url not in seen:
            seen.add(link.url)
            docs.append((link.url, link.text))
    return docs


def split_designator_title(index_text: str, doc_url: str) -> tuple[str, str]:
    if "," in index_text:
        designator, title = index_text.split(",", 1)
        return designator.strip(), title.strip()
    tail = normalized_path(doc_url).strip("/").split("/")[-1].upper()
    return tail, index_text.strip()


def doc_type_from_designator(designator: str) -> str:
    match = DOCTYPE_RE.match(designator.strip())
    if match:
        return match.group(1).upper()
    return designator.split(" ", 1)[0].upper() if designator else ""


def classify(title: str, designator: str) -> str:
    text = f"{designator} {title}".lower()
    scores: list[tuple[int, str]] = []
    for category, keywords in CATEGORY_RULES:
        score = sum(1 for keyword in keywords if keyword in text)
        if score:
            scores.append((score, category))
    if not scores:
        return "General standards and recommended practices"
    scores.sort(key=lambda item: (-item[0], item[1]))
    return scores[0][1]


def extract_family(designator: str) -> str:
    match = FAMILY_RE.match(designator.strip().upper())
    if not match:
        return ""
    return f"{match.group(1)} {match.group(2)}"


def unique_sorted(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        normalized = " ".join(value.split())
        if normalized:
            seen.setdefault(normalized.lower(), normalized)
    return sorted(seen.values(), key=str.lower)


def extract_tags(designator: str, title: str, category: str) -> list[str]:
    text = f"{designator} {title}".lower()
    tags: list[str] = []
    for triggers, values in KEYWORD_RULES:
        if any(trigger in text for trigger in triggers):
            tags.extend(values)

    if not tags and category != "General standards and recommended practices":
        tags.append(category.split(",", 1)[0])
    return unique_sorted(tags)


def extract_aliases(tags: list[str], designator: str, title: str, family: str) -> list[str]:
    aliases: list[str] = [designator, family, title]
    for tag in tags:
        aliases.append(tag)
        aliases.extend(TAG_ALIASES.get(tag, ()))
    return unique_sorted(aliases)


def build_search_text(
    designator: str,
    title: str,
    category: str,
    doc_type: str,
    family: str,
    tags: list[str],
    aliases: list[str],
    status: str,
    latest_date: str,
) -> str:
    return " ".join(
        value
        for value in [
            designator,
            title,
            category,
            doc_type,
            family,
            " ".join(tags),
            " ".join(aliases),
            status,
            latest_date,
        ]
        if value
    )


def version_kind(label: str) -> str:
    lower = label.lower()
    if "amend" in lower or "-am" in lower:
        return "amendment"
    if "withdraw" in lower:
        return "withdrawal"
    if "corrigend" in lower or "-cor" in lower:
        return "corrigendum"
    return "publication"


def extract_versions(doc_url: str, doc_html: str) -> tuple[str, list[Version]]:
    parser = parse_page(doc_url, doc_html)
    versions: list[Version] = []
    seen: set[str] = set()
    for link in parser.links:
        if link.url in seen:
            continue
        if VERSION_RE.match(normalized_path(link.url)):
            seen.add(link.url)
            date_match = DATE_RE.search(link.text)
            versions.append(
                Version(
                    label=link.text,
                    date=date_match.group(1) if date_match else "",
                    url=link.url,
                    kind=version_kind(link.text + " " + normalized_path(link.url)),
                )
            )
    versions.sort(key=lambda item: item.date, reverse=True)
    return parser.status, versions


def build_record(doc_url: str, index_text: str, doc_html: str) -> DocumentRecord:
    designator, title = split_designator_title(index_text, doc_url)
    status, versions = extract_versions(doc_url, doc_html)
    latest = versions[0] if versions else Version("", "", "", "")
    doc_type = doc_type_from_designator(designator)
    category = classify(title, designator)
    family = extract_family(designator)
    tags = extract_tags(designator, title, category)
    aliases = extract_aliases(tags, designator, title, family)
    normalized_status = status or "unknown"
    return DocumentRecord(
        designator=designator,
        title=title,
        doc_type=doc_type,
        category=category,
        family=family,
        tags=tags,
        aliases=aliases,
        search_text=build_search_text(
            designator,
            title,
            category,
            doc_type,
            family,
            tags,
            aliases,
            normalized_status,
            latest.date,
        ),
        status=normalized_status,
        doc_url=doc_url,
        version_count=len(versions),
        latest_date=latest.date,
        latest_url=latest.url,
        versions=versions,
        source=INDEX_URL,
    )


def write_csv(path: Path, records: list[DocumentRecord]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "designator",
                "title",
                "doc_type",
                "category",
                "family",
                "tags",
                "aliases",
                "status",
                "version_count",
                "latest_date",
                "doc_url",
                "latest_url",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "designator": record.designator,
                    "title": record.title,
                    "doc_type": record.doc_type,
                    "category": record.category,
                    "family": record.family,
                    "tags": "; ".join(record.tags),
                    "aliases": "; ".join(record.aliases),
                    "status": record.status,
                    "version_count": record.version_count,
                    "latest_date": record.latest_date,
                    "doc_url": record.doc_url,
                    "latest_url": record.latest_url,
                }
            )


def write_json(path: Path, records: list[DocumentRecord]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump([asdict(record) for record in records], handle, ensure_ascii=False, indent=2)


def write_html(path: Path, records: list[DocumentRecord], generated_at: str) -> None:
    data_json = json.dumps([asdict(record) for record in records], ensure_ascii=False)
    categories = sorted({record.category for record in records})
    tags = sorted({tag for record in records for tag in record.tags}, key=str.lower)
    families = sorted({record.family for record in records if record.family}, key=natural_key)
    doc_types = sorted({record.doc_type for record in records if record.doc_type})
    statuses = sorted({record.status for record in records if record.status})
    category_options = "\n".join(
        f'<option value="{html.escape(category)}">{html.escape(category)}</option>'
        for category in categories
    )
    type_options = "\n".join(
        f'<option value="{html.escape(doc_type)}">{html.escape(doc_type)}</option>'
        for doc_type in doc_types
    )
    tag_options = "\n".join(
        f'<option value="{html.escape(tag)}">{html.escape(tag)}</option>'
        for tag in tags
    )
    family_options = "\n".join(
        f'<option value="{html.escape(family)}">{html.escape(family)}</option>'
        for family in families
    )
    status_options = "\n".join(
        f'<option value="{html.escape(status)}">{html.escape(status)}</option>'
        for status in statuses
    )
    path.write_text(
        HTML_TEMPLATE.replace("__DATA__", data_json)
        .replace("__GENERATED_AT__", html.escape(generated_at))
        .replace("__CATEGORY_OPTIONS__", category_options)
        .replace("__TAG_OPTIONS__", tag_options)
        .replace("__FAMILY_OPTIONS__", family_options)
        .replace("__TYPE_OPTIONS__", type_options)
        .replace("__STATUS_OPTIONS__", status_options),
        encoding="utf-8",
    )


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SMPTE Public Document Index</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #607080;
      --line: #d9e0e7;
      --accent: #0f6c81;
      --accent-soft: #e3f3f6;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 "Segoe UI", Arial, sans-serif;
    }
    header {
      padding: 22px 28px 16px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0 0 6px;
      font-size: 24px;
      font-weight: 650;
      letter-spacing: 0;
    }
    .meta { color: var(--muted); }
    main { padding: 18px 28px 32px; }
    .toolbar {
      display: grid;
      grid-template-columns: minmax(260px, 1.4fr) 220px 180px 150px 120px 150px;
      gap: 10px;
      margin-bottom: 12px;
    }
    input, select {
      width: 100%;
      min-height: 36px;
      padding: 7px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
    }
    .summary {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 14px;
      color: var(--muted);
    }
    .chip {
      padding: 4px 8px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: #164d59;
      border: 1px solid #c8e8ee;
    }
    .tag-stats {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin: 0 0 14px;
    }
    .tag-stat {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      border-radius: 999px;
      padding: 5px 9px;
      cursor: pointer;
      font: inherit;
    }
    .tag-stat:hover,
    .tag-stat.active {
      border-color: #8cc5d0;
      background: var(--accent-soft);
      color: #164d59;
    }
    .tag-stat span { color: var(--muted); }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
    }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #eef3f7;
      font-weight: 650;
      white-space: nowrap;
    }
    td.small { color: var(--muted); white-space: nowrap; }
    .title { min-width: 340px; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .category {
      display: inline-block;
      max-width: 260px;
      padding: 3px 7px;
      border-radius: 5px;
      background: #edf2f7;
    }
    .tags {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      min-width: 220px;
      max-width: 360px;
    }
    .tag {
      display: inline-block;
      padding: 2px 6px;
      border-radius: 5px;
      background: #e8f1f4;
      color: #164d59;
      border: 1px solid #c9dde3;
      font-size: 12px;
      line-height: 1.35;
      white-space: nowrap;
    }
    @media (max-width: 980px) {
      main, header { padding-left: 14px; padding-right: 14px; }
      .toolbar { grid-template-columns: 1fr; }
      table { font-size: 13px; }
      .hide-mobile { display: none; }
    }
  </style>
</head>
<body>
  <header>
    <h1>SMPTE Public Document Index</h1>
    <div class="meta">Generated at __GENERATED_AT__ from https://pub.smpte.org/doc/</div>
  </header>
  <main>
    <div class="toolbar">
      <input id="query" type="search" placeholder="Search designator, title, keyword, family">
      <select id="category">
        <option value="">All categories</option>
        __CATEGORY_OPTIONS__
      </select>
      <select id="tag">
        <option value="">All keywords</option>
        __TAG_OPTIONS__
      </select>
      <select id="family">
        <option value="">All families</option>
        __FAMILY_OPTIONS__
      </select>
      <select id="doctype">
        <option value="">All types</option>
        __TYPE_OPTIONS__
      </select>
      <select id="status">
        <option value="">All status</option>
        __STATUS_OPTIONS__
      </select>
    </div>
    <div class="summary">
      <span class="chip"><span id="count"></span> visible</span>
      <span class="chip"><span id="total"></span> total</span>
      <span class="chip">Multi-word search uses AND matching</span>
    </div>
    <div id="tagStats" class="tag-stats"></div>
    <table>
      <thead>
        <tr>
          <th>Designator</th>
          <th class="title">Title</th>
          <th>Keywords</th>
          <th>Category</th>
          <th>Family</th>
          <th>Type</th>
          <th>Status</th>
          <th>Latest</th>
          <th class="hide-mobile">Versions</th>
        </tr>
      </thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script>
    const records = __DATA__;
    const rows = document.getElementById("rows");
    const query = document.getElementById("query");
    const category = document.getElementById("category");
    const tag = document.getElementById("tag");
    const family = document.getElementById("family");
    const doctype = document.getElementById("doctype");
    const status = document.getElementById("status");
    const tagStats = document.getElementById("tagStats");
    const count = document.getElementById("count");
    const total = document.getElementById("total");
    total.textContent = records.length;

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[c]));
    }

    function tokenizeQuery(value) {
      return value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
    }

    function matches(record) {
      const terms = tokenizeQuery(query.value);
      const haystack = String(record.search_text || [
        record.designator,
        record.title,
        record.category,
        record.doc_type,
        record.family,
        record.status,
        record.latest_date,
        ...(record.tags || []),
        ...(record.aliases || [])
      ].join(" ")).toLowerCase();
      return terms.every(term => haystack.includes(term))
        && (!category.value || record.category === category.value)
        && (!tag.value || (record.tags || []).includes(tag.value))
        && (!family.value || record.family === family.value)
        && (!doctype.value || record.doc_type === doctype.value)
        && (!status.value || record.status === status.value);
    }

    function countTags(items) {
      const counts = new Map();
      for (const record of items) {
        for (const value of record.tags || []) {
          counts.set(value, (counts.get(value) || 0) + 1);
        }
      }
      return [...counts.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, 24);
    }

    function renderTagStats(items) {
      const stats = countTags(items);
      tagStats.innerHTML = stats.map(([name, value]) => `
        <button class="tag-stat ${tag.value === name ? "active" : ""}" data-tag="${esc(name)}">
          ${esc(name)} <span>${esc(value)}</span>
        </button>
      `).join("");
      tagStats.querySelectorAll("button").forEach(button => {
        button.addEventListener("click", () => {
          tag.value = tag.value === button.dataset.tag ? "" : button.dataset.tag;
          render();
        });
      });
    }

    function render() {
      const filtered = records.filter(matches);
      count.textContent = filtered.length;
      renderTagStats(filtered);
      rows.innerHTML = filtered.map(record => `
        <tr>
          <td class="small"><a href="${esc(record.doc_url)}">${esc(record.designator)}</a></td>
          <td>${esc(record.title)}</td>
          <td><div class="tags">${(record.tags || []).map(value => `<span class="tag">${esc(value)}</span>`).join("")}</div></td>
          <td><span class="category">${esc(record.category)}</span></td>
          <td class="small">${esc(record.family)}</td>
          <td class="small">${esc(record.doc_type)}</td>
          <td class="small">${esc(record.status)}</td>
          <td class="small">${record.latest_url ? `<a href="${esc(record.latest_url)}">${esc(record.latest_date || "latest")}</a>` : ""}</td>
          <td class="small hide-mobile">${esc(record.version_count)}</td>
        </tr>
      `).join("");
    }

    [query, category, tag, family, doctype, status].forEach(el => el.addEventListener("input", render));
    render();
  </script>
</body>
</html>
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    log(f"Fetching SMPTE index: {args.index_url}")
    index_html = fetch_text(args.index_url, args.user_agent, args.timeout, args.retries, args.delay)
    docs = discover_docs(args.index_url, index_html)
    if args.max_docs is not None:
        docs = docs[: args.max_docs]
    log(f"Found {len(docs)} document pages")

    records: list[DocumentRecord] = []
    failures: list[dict[str, str]] = []
    for index, (doc_url, index_text) in enumerate(docs, start=1):
        log(f"[{index}/{len(docs)}] {index_text}")
        try:
            doc_html = fetch_text(doc_url, args.user_agent, args.timeout, args.retries, args.delay)
            records.append(build_record(doc_url, index_text, doc_html))
        except Exception as exc:
            failures.append({"doc_url": doc_url, "title": index_text, "error": str(exc)})
        time.sleep(args.delay)

    records.sort(key=lambda record: (record.doc_type, natural_key(record.designator)))
    generated_at = utc_now()
    write_csv(output_dir / "smpte_index.csv", records)
    write_json(output_dir / "smpte_index.json", records)
    write_html(output_dir / "index.html", records, generated_at)
    if failures:
        with (output_dir / "failures.json").open("w", encoding="utf-8") as handle:
            json.dump(failures, handle, ensure_ascii=False, indent=2)

    log(f"Done. Records: {len(records)}, failures: {len(failures)}")
    log(f"HTML: {output_dir / 'index.html'}")
    log(f"CSV:  {output_dir / 'smpte_index.csv'}")
    log(f"JSON: {output_dir / 'smpte_index.json'}")
    return 1 if failures else 0


def natural_key(text: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
