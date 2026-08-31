#!/usr/bin/env python3
"""Download public documents from https://pub.smpte.org/doc/.

The SMPTE public library is organized as:

    /doc/                 document index
    /doc/<designator>/    version list
    /doc/<designator>/<version>/  PDF iframe and ZIP archive links

This script follows those public pages, downloads linked files, and writes a
manifest so interrupted runs can be resumed safely.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen


BASE_URL = "https://pub.smpte.org"
INDEX_URL = f"{BASE_URL}/doc/"
DEFAULT_USER_AGENT = (
    "ClassicColour-Utils SMPTE public document archiver "
    "(contact: local research use)"
)
DOWNLOAD_EXTENSIONS = {
    ".pdf",
    ".zip",
    ".xml",
    ".xsd",
    ".xlsx",
    ".xls",
    ".csv",
    ".txt",
    ".doc",
    ".docx",
}
VERSION_RE = re.compile(r"^/doc/[^/]+/\d{8}[^/]*/$")
DOC_RE = re.compile(r"^/doc/[^/]+/$")


@dataclass(frozen=True)
class Link:
    url: str
    text: str
    tag: str
    attr: str


@dataclass(frozen=True)
class DownloadItem:
    doc_url: str
    version_url: str
    file_url: str
    local_path: Path


class LinkParser(HTMLParser):
    """Small HTML link extractor for href/src attributes."""

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.links: list[Link] = []
        self._current: dict[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value for name, value in attrs if value}
        for attr in ("href", "src"):
            value = attr_map.get(attr)
            if value:
                absolute = urljoin(self.page_url, html.unescape(value))
                self._current = {"url": absolute, "tag": tag, "attr": attr}
                self._text = []
                if tag.lower() in {"iframe", "img", "source", "script", "link"}:
                    self.links.append(Link(absolute, "", tag.lower(), attr))
                break

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        current_tag = self._current["tag"]
        if tag.lower() == current_tag.lower():
            text = " ".join("".join(self._text).split())
            self.links.append(
                Link(
                    url=self._current["url"],
                    text=text,
                    tag=current_tag.lower(),
                    attr=self._current["attr"],
                )
            )
            self._current = None
            self._text = []


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download all publicly linked SMPTE documents from pub.smpte.org/doc/."
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(Path(__file__).resolve().parent / "downloads"),
        help="Download directory. Default: parse_smpte/downloads",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Manifest CSV path. Default: <output>/manifest.csv",
    )
    parser.add_argument(
        "--index-url",
        default=INDEX_URL,
        help=f"SMPTE index URL. Default: {INDEX_URL}",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.3,
        help="Seconds to wait between HTTP requests. Default: 0.3",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="HTTP timeout in seconds. Default: 60",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retries per request. Default: 3",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="HTTP User-Agent header.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover files and write manifest without downloading file bodies.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Download even when the target file already exists.",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=None,
        help="Limit number of document pages for testing.",
    )
    parser.add_argument(
        "--max-downloads",
        type=int,
        default=None,
        help="Limit number of discovered downloads for testing.",
    )
    return parser.parse_args(argv)


def log(message: str) -> None:
    print(message, flush=True)


def same_host(url: str, index_url: str) -> bool:
    return urlparse(url).netloc == urlparse(index_url).netloc


def normalized_path(url: str) -> str:
    path = urlparse(url).path
    if not path.startswith("/"):
        path = "/" + path
    return path


def fetch_bytes(
    url: str,
    *,
    user_agent: str,
    timeout: float,
    retries: int,
    delay: float,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers={"User-Agent": user_agent})
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            sleep_for = delay * attempt + 0.5
            log(f"  retry {attempt}/{retries} after {type(exc).__name__}: {url}")
            time.sleep(sleep_for)
    raise RuntimeError(f"failed to fetch {url}: {last_error}") from last_error


def fetch_text(
    url: str,
    *,
    user_agent: str,
    timeout: float,
    retries: int,
    delay: float,
) -> str:
    data = fetch_bytes(
        url,
        user_agent=user_agent,
        timeout=timeout,
        retries=retries,
        delay=delay,
    )
    return data.decode("utf-8", errors="replace")


def extract_links(page_url: str, content: str) -> list[Link]:
    parser = LinkParser(page_url)
    parser.feed(content)
    return parser.links


def unique_in_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def discover_doc_urls(index_url: str, html_text: str) -> list[str]:
    urls = []
    for link in extract_links(index_url, html_text):
        path = normalized_path(link.url)
        if DOC_RE.match(path) and path != "/doc/":
            urls.append(link.url)
    return unique_in_order(urls)


def discover_version_urls(doc_url: str, html_text: str) -> list[str]:
    urls = []
    for link in extract_links(doc_url, html_text):
        path = normalized_path(link.url)
        if VERSION_RE.match(path):
            urls.append(link.url)
    return unique_in_order(urls)


def has_download_extension(url: str) -> bool:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    return suffix in DOWNLOAD_EXTENSIONS


def discover_download_urls(version_url: str, html_text: str, index_url: str) -> list[str]:
    urls = []
    for link in extract_links(version_url, html_text):
        if same_host(link.url, index_url) and has_download_extension(link.url):
            urls.append(link.url)
    return unique_in_order(urls)


def local_path_for(output_dir: Path, file_url: str) -> Path:
    parsed = urlparse(file_url)
    parts = [part for part in unquote(parsed.path).split("/") if part]
    if not parts:
        raise ValueError(f"cannot derive local path from {file_url}")
    return output_dir.joinpath(*sanitize_path_parts(parts))


def sanitize_path_parts(parts: list[str]) -> list[str]:
    sanitized = []
    for part in parts:
        safe = re.sub(r'[<>:"|?*\x00-\x1f]', "_", part).strip()
        safe = safe.rstrip(". ")
        sanitized.append(safe or "_")
    return sanitized


def write_manifest(manifest_path: Path, rows: list[dict[str, str]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "status",
        "doc_url",
        "version_url",
        "file_url",
        "local_path",
        "size_bytes",
        "timestamp_utc",
        "error",
    ]
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json_manifest(manifest_path: Path, rows: list[dict[str, str]]) -> None:
    json_path = manifest_path.with_suffix(".json")
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)


def download_file(
    item: DownloadItem,
    *,
    user_agent: str,
    timeout: float,
    retries: int,
    delay: float,
    force: bool,
    dry_run: bool,
) -> tuple[str, int, str]:
    if item.local_path.exists() and not force:
        return "skipped_exists", item.local_path.stat().st_size, ""
    if dry_run:
        return "dry_run", 0, ""

    data = fetch_bytes(
        item.file_url,
        user_agent=user_agent,
        timeout=timeout,
        retries=retries,
        delay=delay,
    )
    item.local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = item.local_path.with_suffix(item.local_path.suffix + ".part")
    with tmp_path.open("wb") as handle:
        handle.write(data)
    os.replace(tmp_path, item.local_path)
    return "downloaded", len(data), ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output).resolve()
    manifest_path = Path(args.manifest).resolve() if args.manifest else output_dir / "manifest.csv"
    rows: list[dict[str, str]] = []
    discovered = 0
    failures = 0

    log(f"Fetching index: {args.index_url}")
    index_html = fetch_text(
        args.index_url,
        user_agent=args.user_agent,
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
    )
    doc_urls = discover_doc_urls(args.index_url, index_html)
    if args.max_docs is not None:
        doc_urls = doc_urls[: args.max_docs]
    log(f"Found {len(doc_urls)} document pages")
    time.sleep(args.delay)

    for doc_index, doc_url in enumerate(doc_urls, start=1):
        log(f"[{doc_index}/{len(doc_urls)}] {doc_url}")
        try:
            doc_html = fetch_text(
                doc_url,
                user_agent=args.user_agent,
                timeout=args.timeout,
                retries=args.retries,
                delay=args.delay,
            )
            version_urls = discover_version_urls(doc_url, doc_html)
        except Exception as exc:
            failures += 1
            rows.append(error_row("doc_failed", doc_url, "", "", "", str(exc)))
            write_manifest(manifest_path, rows)
            write_json_manifest(manifest_path, rows)
            continue

        time.sleep(args.delay)
        for version_url in version_urls:
            if args.max_downloads is not None and discovered >= args.max_downloads:
                break
            try:
                version_html = fetch_text(
                    version_url,
                    user_agent=args.user_agent,
                    timeout=args.timeout,
                    retries=args.retries,
                    delay=args.delay,
                )
                file_urls = discover_download_urls(version_url, version_html, args.index_url)
            except Exception as exc:
                failures += 1
                rows.append(error_row("version_failed", doc_url, version_url, "", "", str(exc)))
                write_manifest(manifest_path, rows)
                write_json_manifest(manifest_path, rows)
                continue

            time.sleep(args.delay)
            for file_url in file_urls:
                if args.max_downloads is not None and discovered >= args.max_downloads:
                    break
                discovered += 1
                local_path = local_path_for(output_dir, file_url)
                item = DownloadItem(doc_url, version_url, file_url, local_path)
                try:
                    status, size, error = download_file(
                        item,
                        user_agent=args.user_agent,
                        timeout=args.timeout,
                        retries=args.retries,
                        delay=args.delay,
                        force=args.force,
                        dry_run=args.dry_run,
                    )
                except Exception as exc:
                    failures += 1
                    status, size, error = "download_failed", 0, str(exc)
                rows.append(
                    {
                        "status": status,
                        "doc_url": doc_url,
                        "version_url": version_url,
                        "file_url": file_url,
                        "local_path": str(local_path),
                        "size_bytes": str(size),
                        "timestamp_utc": utc_now(),
                        "error": error,
                    }
                )
                write_manifest(manifest_path, rows)
                write_json_manifest(manifest_path, rows)
                log(f"  {status}: {file_url}")
                time.sleep(args.delay)

        if args.max_downloads is not None and discovered >= args.max_downloads:
            break

    log(f"Done. Discovered {discovered} files, failures: {failures}")
    log(f"Manifest: {manifest_path}")
    return 1 if failures else 0


def error_row(
    status: str,
    doc_url: str,
    version_url: str,
    file_url: str,
    local_path: str,
    error: str,
) -> dict[str, str]:
    return {
        "status": status,
        "doc_url": doc_url,
        "version_url": version_url,
        "file_url": file_url,
        "local_path": local_path,
        "size_bytes": "0",
        "timestamp_utc": utc_now(),
        "error": error,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
