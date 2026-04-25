#!/usr/bin/env python3
"""
PDF → Kindle EPUB converter.

Usage:
  python convert.py paper.pdf
  python convert.py paper.pdf -o my-paper.epub
  python convert.py paper.pdf --pages 1-10
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from extractor import PDFExtractor
from builder import EPUBBuilder


def convert(
    pdf_path: str,
    output_path: Optional[str] = None,
    page_range: Optional[tuple[int, int]] = None,
    verbose: bool = True,
) -> str:
    src = Path(pdf_path)
    if not src.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    dst = Path(output_path) if output_path else src.with_suffix(".epub")

    if verbose:
        print(f"Reading  : {src}")

    extractor = PDFExtractor(str(src))

    if verbose:
        print(f"Body size: {extractor.body_size:.1f}pt  |  "
              f"Pages: {len(extractor.doc)}")

    doc = extractor.extract()

    # Optional page slice
    if page_range:
        start, end = page_range
        doc.pages = [p for p in doc.pages if start <= p.number + 1 <= end]

    if not doc.pages:
        raise ValueError("No pages to convert.")

    if verbose:
        print(f"Title    : {doc.title}")
        blocks_total = sum(len(p.blocks) for p in doc.pages)
        print(f"Blocks   : {blocks_total}  ({len(doc.pages)} pages)")

    builder = EPUBBuilder(doc)
    builder.build(str(dst))

    if verbose:
        size_kb = dst.stat().st_size // 1024
        imgs = len(builder._images)
        print(f"Output   : {dst}  ({size_kb} KB, {imgs} image(s))")
        _print_instructions(dst)

    return str(dst)


def _print_instructions(epub_path: Path) -> None:
    print()
    print("── Send to Kindle ──────────────────────────────────────────")
    print(f"  File : {epub_path.name}")
    print()
    print("  Option A – Email")
    print("    Attach the .epub to an email and send it to your")
    print("    Kindle email address (found in Amazon > Manage Your")
    print("    Content and Devices > Preferences > Personal Document")
    print("    Settings).")
    print()
    print("  Option B – Send to Kindle app (Mac / Windows / web)")
    print("    Open https://www.amazon.com/sendtokindle")
    print("    or use the desktop/mobile 'Send to Kindle' app.")
    print()
    print("  Option C – USB")
    print("    Copy the .epub to the 'documents' folder on your Kindle.")
    print("────────────────────────────────────────────────────────────")


def _parse_page_range(s: str) -> tuple[int, int]:
    parts = s.split("-")
    if len(parts) == 1:
        n = int(parts[0])
        return (n, n)
    return (int(parts[0]), int(parts[1]))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert an academic PDF to a Kindle-optimised EPUB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Output .epub path (default: same directory as PDF)",
    )
    parser.add_argument(
        "--pages",
        metavar="N or N-M",
        help="Convert only a page range, e.g. --pages 1-12",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()

    page_range = _parse_page_range(args.pages) if args.pages else None

    try:
        convert(
            pdf_path=args.pdf,
            output_path=args.output,
            page_range=page_range,
            verbose=not args.quiet,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
