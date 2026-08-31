# SMPTE public document scraper

This folder contains a crawler for the public SMPTE document library:

https://pub.smpte.org/doc/

The script walks the public index, visits every document version page, and
downloads linked public files such as PDFs and ZIP archives.

## Usage

Run a small discovery test without downloading file bodies:

```powershell
python .\parse_smpte\scrape_smpte.py --dry-run --max-docs 2 --max-downloads 4
```

Run the full crawl:

```powershell
python .\parse_smpte\scrape_smpte.py
```

By default, files are saved under:

```text
parse_smpte/downloads/
```

The script preserves the URL path below that directory. For example:

```text
parse_smpte/downloads/doc/st12-1/20140220-pub/st0012-1-2014.pdf
```

## Resume behavior

Existing files are skipped by default, so you can rerun the same command after
an interruption. Use `--force` to redownload existing files.

Each run writes:

```text
parse_smpte/downloads/manifest.csv
parse_smpte/downloads/manifest.json
```

The manifest records source document URL, version URL, file URL, local path,
status, size, timestamp, and any error.

## Useful options

```powershell
python .\parse_smpte\scrape_smpte.py --output D:\smpte_docs
python .\parse_smpte\scrape_smpte.py --delay 1.0
python .\parse_smpte\scrape_smpte.py --timeout 120 --retries 5
python .\parse_smpte\scrape_smpte.py --force
```

Use a larger `--delay` if you want to be more conservative with request rate.

## Build a searchable document index

Generate a local HTML/CSV/JSON index for quick search and classification without
downloading all PDF bodies:

```powershell
python .\parse_smpte\build_smpte_index.py
```

Default output:

```text
parse_smpte/index_site/index.html
parse_smpte/index_site/smpte_index.csv
parse_smpte/index_site/smpte_index.json
```

The HTML index supports:

- multi-word search with AND matching, for example `mxf metadata`
- category, keyword, document family, type, and status filters
- inferred keywords such as `MXF`, `IMF`, `HDR`, `Timecode`, `Metadata`, `SDI`
- top keyword statistics for a quick overview of SMPTE document areas

Run a small test index:

```powershell
python .\parse_smpte\build_smpte_index.py --max-docs 20
```
