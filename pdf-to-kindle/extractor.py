"""PDF extraction with two-column layout detection and reading-order reflow."""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import fitz  # PyMuPDF


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class FontSpan:
    text: str
    size: float
    flags: int  # 1=superscript, 2=italic, 8=monospace, 16=bold

    @property
    def bold(self) -> bool:
        return bool(self.flags & 16)

    @property
    def italic(self) -> bool:
        return bool(self.flags & 2)


@dataclass
class TextBlock:
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str = "text"
    lines: List[List[FontSpan]] = field(default_factory=list)
    dominant_size: float = 12.0
    level: str = "body"  # h1 | h2 | h3 | body | caption | footnote

    def text(self) -> str:
        parts = []
        for line in self.lines:
            parts.append("".join(s.text for s in line))
        return " ".join(p for p in parts if p.strip())


@dataclass
class ImageBlock:
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str = "image"
    data: bytes = b""
    ext: str = "png"
    orig_width: int = 0
    orig_height: int = 0


@dataclass
class TableBlock:
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str = "table"
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    # Fallback: rendered as image when cell-level extraction fails
    image_data: Optional[bytes] = None


Block = TextBlock | ImageBlock | TableBlock


@dataclass
class ParsedPage:
    number: int
    blocks: List[Block]


@dataclass
class ParsedDoc:
    title: str = ""
    pages: List[ParsedPage] = field(default_factory=list)


# ── Extractor ─────────────────────────────────────────────────────────────────

class PDFExtractor:
    def __init__(self, path: str):
        self.doc = fitz.open(path)
        self.body_size = self._detect_body_size()

    # ── Font analysis ──────────────────────────────────────────────────────────

    def _detect_body_size(self) -> float:
        sizes: list[float] = []
        for page in self.doc:
            for block in page.get_text("dict")["blocks"]:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        if span["text"].strip():
                            sizes.append(round(span["size"], 1))
        if not sizes:
            return 10.0
        counts = Counter(sizes)
        return counts.most_common(1)[0][0]

    def _classify(self, size: float, text: str, flags: int) -> str:
        ratio = size / self.body_size
        if ratio >= 1.5:
            return "h1"
        if ratio >= 1.25:
            return "h2"
        # Bold same-size text acting as a heading
        if ratio >= 0.95 and (flags & 16):
            return "h3"
        if ratio >= 1.08:
            return "h3"
        if ratio <= 0.82:
            if re.match(r"^(fig(ure)?\.?|table|tab\.?|figura)\s*\d+", text, re.I):
                return "caption"
            return "footnote"
        return "body"

    # ── Column detection ───────────────────────────────────────────────────────

    def _column_split(self, raw_blocks: list, page_w: float) -> Optional[float]:
        """Return x-coordinate where the 2nd column starts, or None."""
        x_starts = [b["bbox"][0] for b in raw_blocks if b["type"] == 0]
        if len(x_starts) < 5:
            return None

        # Blocks that start in the "right half zone" (roughly 30–72 % of page)
        mid = [x for x in x_starts if 0.28 * page_w < x < 0.72 * page_w]
        if len(mid) < 3:
            return None

        # Cluster with 10-px buckets and pick the dominant start
        buckets = Counter(round(x / 10) * 10 for x in mid)
        best_x, count = buckets.most_common(1)[0]
        if count >= 3 and 0.28 * page_w < best_x < 0.68 * page_w:
            return float(best_x)
        return None

    # ── Block parsing ──────────────────────────────────────────────────────────

    def _parse_text_block(self, block: dict) -> Optional[TextBlock]:
        lines: list[list[FontSpan]] = []
        max_size = 0.0
        combined_flags = 0

        for raw_line in block["lines"]:
            spans = []
            for s in raw_line["spans"]:
                if not s["text"].strip():
                    continue
                fs = FontSpan(
                    text=s["text"],
                    size=round(s["size"], 1),
                    flags=s["flags"],
                )
                spans.append(fs)
                if s["size"] > max_size:
                    max_size = s["size"]
                combined_flags |= s["flags"]
            if spans:
                lines.append(spans)

        if not lines:
            return None
        if not max_size:
            max_size = self.body_size

        tb = TextBlock(
            x0=block["bbox"][0],
            y0=block["bbox"][1],
            x1=block["bbox"][2],
            y1=block["bbox"][3],
            lines=lines,
            dominant_size=max_size,
        )
        tb.level = self._classify(max_size, tb.text(), combined_flags)
        return tb

    def _extract_images(self, page: fitz.Page) -> List[Tuple[fitz.Rect, bytes, str]]:
        results: list[tuple[fitz.Rect, bytes, str]] = []
        seen: set[int] = set()
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                img_dict = self.doc.extract_image(xref)
                if not img_dict or not img_dict.get("image"):
                    continue
                results.append((rects[0], img_dict["image"], img_dict.get("ext", "png")))
            except Exception:
                continue
        return results

    def _extract_tables(self, page: fitz.Page) -> Tuple[List[TableBlock], set]:
        """Returns (table_blocks, set_of_table_rects_as_tuples)."""
        tables: list[TableBlock] = []
        table_rects: set[tuple] = set()

        try:
            finder = page.find_tables()
        except Exception:
            return tables, table_rects

        for tbl in finder.tables:
            rect = tbl.bbox
            table_rects.add(tuple(map(lambda v: round(v, 1), rect)))

            tb = TableBlock(x0=rect[0], y0=rect[1], x1=rect[2], y1=rect[3])
            try:
                extracted = tbl.extract()
                if extracted:
                    tb.headers = [str(c or "").strip() for c in extracted[0]]
                    tb.rows = [
                        [str(c or "").strip() for c in row]
                        for row in extracted[1:]
                    ]
            except Exception:
                # Fall back to rendering the table area as an image
                try:
                    clip = fitz.Rect(rect)
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip)
                    tb.image_data = pix.tobytes("png")
                except Exception:
                    pass

            tables.append(tb)

        return tables, table_rects

    # ── Reading-order reflow ───────────────────────────────────────────────────

    def _reorder(
        self,
        text_blocks: List[TextBlock],
        image_blocks: List[ImageBlock],
        table_blocks: List[TableBlock],
        page_w: float,
        raw_blocks: list,
    ) -> List[Block]:
        split_x = self._column_split(raw_blocks, page_w)

        all_blocks: list[Block] = text_blocks + image_blocks + table_blocks  # type: ignore

        if split_x is None:
            return sorted(all_blocks, key=lambda b: (b.y0, b.x0))

        full_width: list[Block] = []
        left_col: list[Block] = []
        right_col: list[Block] = []

        for b in all_blocks:
            w = b.x1 - b.x0
            if w > page_w * 0.55:
                full_width.append(b)
            elif b.x0 < split_x:
                left_col.append(b)
            else:
                right_col.append(b)

        full_width.sort(key=lambda b: b.y0)
        left_col.sort(key=lambda b: b.y0)
        right_col.sort(key=lambda b: b.y0)

        if not full_width:
            return left_col + right_col

        result: list[Block] = []
        prev_y = 0.0

        for fw in full_width:
            lc = sorted(
                [b for b in left_col if prev_y <= b.y0 < fw.y0], key=lambda b: b.y0
            )
            rc = sorted(
                [b for b in right_col if prev_y <= b.y0 < fw.y0], key=lambda b: b.y0
            )
            result.extend(lc)
            result.extend(rc)
            result.append(fw)
            prev_y = fw.y1

        result.extend(sorted([b for b in left_col if b.y0 >= prev_y], key=lambda b: b.y0))
        result.extend(sorted([b for b in right_col if b.y0 >= prev_y], key=lambda b: b.y0))
        return result

    # ── Page number / header / footer filter ───────────────────────────────────

    def _is_boilerplate(self, tb: TextBlock, page_h: float) -> bool:
        """Heuristic to skip page numbers, running headers/footers."""
        text = tb.text().strip()
        if not text:
            return True
        # Narrow margin: only flag very short text near extreme edges
        # (page numbers, journal name, DOI lines in header/footer)
        bottom_margin = tb.y0 > page_h * 0.93
        top_margin = tb.y1 < page_h * 0.04
        if (top_margin or bottom_margin) and len(text) < 40:
            return True
        return False

    # ── Main extraction ────────────────────────────────────────────────────────

    def extract(self) -> ParsedDoc:
        result = ParsedDoc()

        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            page_w = page.rect.width
            page_h = page.rect.height

            raw_dict = page.get_text("dict")
            raw_blocks = raw_dict["blocks"]

            table_blocks, table_rects = self._extract_tables(page)

            def _in_table(bbox) -> bool:
                bx0, by0, bx1, by1 = bbox
                for tx0, ty0, tx1, ty1 in table_rects:
                    if bx0 >= tx0 - 2 and by0 >= ty0 - 2 and bx1 <= tx1 + 2 and by1 <= ty1 + 2:
                        return True
                return False

            text_blocks: list[TextBlock] = []
            for block in raw_blocks:
                if block["type"] != 0 or _in_table(block["bbox"]):
                    continue
                tb = self._parse_text_block(block)
                if tb and not self._is_boilerplate(tb, page_h):
                    text_blocks.append(tb)

            image_blocks: list[ImageBlock] = []
            for rect, img_data, ext in self._extract_images(page):
                ib = ImageBlock(
                    x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1,
                    data=img_data, ext=ext,
                    orig_width=int(rect.width), orig_height=int(rect.height),
                )
                image_blocks.append(ib)

            ordered = self._reorder(text_blocks, image_blocks, table_blocks, page_w, raw_blocks)

            if page_num == 0 and not result.title:
                for b in ordered:
                    if isinstance(b, TextBlock) and b.level == "h1":
                        result.title = b.text()[:120]
                        break

            result.pages.append(ParsedPage(number=page_num, blocks=ordered))

        if not result.title:
            result.title = "Document"

        return result
