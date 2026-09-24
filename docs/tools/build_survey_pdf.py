"""Regenerates docs/literature-survey-updated-2026-09-24.pdf from its Markdown source.

    markdown source -> HTML (markdown-it-py) -> PDF (headless Microsoft Edge or Chrome)

The original 26 Aug 2026 survey had no source file in the repository (only a
LibreOffice-generated PDF), so the Markdown file next to this one is the new
source of truth. Requirements: `pip install markdown-it-py` and Edge or Chrome.

    python docs/tools/build_survey_pdf.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt

DOCS = Path(__file__).resolve().parent.parent
SOURCE = DOCS / "literature-survey-updated-2026-09-24.md"
OUTPUT = DOCS / "literature-survey-updated-2026-09-24.pdf"

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge",
    "google-chrome",
    "chromium",
]

CSS = """
@page { size: A4; margin: 20mm 18mm 20mm 18mm; }
@page wide { size: A4 landscape; margin: 14mm 12mm; }
html { font-family: Cambria, 'Times New Roman', Georgia, serif; font-size: 10.5pt; line-height: 1.38; color: #111; }
body { margin: 0; }
h1 { font-size: 20pt; text-align: center; margin: 0 0 4pt 0; }
h2 { font-size: 14pt; margin: 18pt 0 6pt 0; border-bottom: 1px solid #999; padding-bottom: 2pt; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt 0; page-break-after: avoid; }
p { margin: 0 0 6pt 0; text-align: justify; }
.titlepage { text-align: center; padding: 30mm 0 10mm 0; page-break-after: always; }
.titlepage h2 { border: none; font-size: 13pt; }
.titlepage p { text-align: center; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt 0; font-size: 8.6pt; line-height: 1.25; }
th, td { border: 1px solid #888; padding: 3pt 4pt; vertical-align: top; text-align: left; overflow-wrap: anywhere; }
th { background: #e8e8e8; }
tr { page-break-inside: avoid; }
.wide { page: wide; }
.wide table { font-size: 7.4pt; }
.wide th:nth-child(2), .wide td:nth-child(2) { white-space: nowrap; }
code { font-family: Consolas, monospace; font-size: 9pt; }
ol, ul { margin: 0 0 6pt 18pt; padding: 0; }
li { margin-bottom: 2pt; text-align: justify; }
a { color: #0b4f9c; text-decoration: none; }
"""


def render_html() -> str:
    text = SOURCE.read_text(encoding="utf-8")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)  # drop YAML front matter
    md = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable("table")
    body = md.render(text)
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Codentry Literature Survey (Updated 2026-09-24)</title><style>{CSS}</style></head><body>{body}</body></html>"


def find_browser() -> str:
    for candidate in BROWSERS:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate
    raise SystemExit("No Edge/Chrome found; install one or print the HTML to PDF manually.")


def main() -> int:
    html = render_html()
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "survey.html"
        html_path.write_text(html, encoding="utf-8")
        profile = Path(tmp) / "profile"
        cmd = [
            find_browser(),
            "--headless",
            "--disable-gpu",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={OUTPUT}",
            html_path.as_uri(),
        ]
        subprocess.run(cmd, check=True, timeout=180, capture_output=True)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
