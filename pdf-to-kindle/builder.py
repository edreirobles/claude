"""EPUB builder optimized for Kindle reading experience."""

import hashlib
import io
import uuid
import zipfile
from typing import List

from PIL import Image as PILImage

from extractor import Block, ImageBlock, ParsedDoc, ParsedPage, TableBlock, TextBlock


# ── Kindle / EPUB constants ────────────────────────────────────────────────────

KINDLE_WIDTH_PX = 758   # Kindle Paperwhite / Scribe usable width
JPEG_QUALITY = 82

CSS = """\
body {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1em;
  line-height: 1.65;
  margin: 0;
  padding: 0 0.4em;
  text-align: justify;
  hyphens: auto;
  -webkit-hyphens: auto;
}
h1 {
  font-size: 1.55em;
  line-height: 1.25;
  margin: 1.2em 0 0.5em;
  text-align: left;
  font-style: normal;
}
h2 {
  font-size: 1.28em;
  line-height: 1.3;
  margin: 1em 0 0.4em;
  text-align: left;
}
h3 {
  font-size: 1.1em;
  margin: 0.9em 0 0.3em;
  text-align: left;
}
p {
  margin: 0 0 0.55em;
  orphans: 2;
  widows: 2;
}
.caption {
  font-size: 0.85em;
  font-style: italic;
  text-align: center;
  margin: 0.15em 0 0.9em;
  color: #444;
}
.footnote {
  font-size: 0.78em;
  color: #555;
  margin: 0.25em 0;
  border-top: 1px solid #bbb;
  padding-top: 0.25em;
}
.figure {
  text-align: center;
  margin: 1em 0;
  page-break-inside: avoid;
}
.figure img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 0 auto;
}
.table-wrap {
  margin: 0.9em 0;
  page-break-inside: avoid;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8em;
}
th {
  background-color: #f0f0f0;
  border: 1px solid #999;
  padding: 4px 6px;
  text-align: left;
  font-weight: bold;
}
td {
  border: 1px solid #ccc;
  padding: 3px 6px;
  vertical-align: top;
}
"""

CONTAINER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
  xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _img_id(data: bytes) -> str:
    return "img_" + hashlib.md5(data).hexdigest()[:12] + ".jpg"


# ── Builder ────────────────────────────────────────────────────────────────────

class EPUBBuilder:
    def __init__(self, doc: ParsedDoc):
        self.doc = doc
        self._images: dict[str, bytes] = {}   # filename → optimised JPEG bytes
        self._uid = str(uuid.uuid4())

    # ── Image optimisation ────────────────────────────────────────────────────

    def _optimise(self, raw: bytes, ext: str) -> bytes:
        """Resize to Kindle width and convert to greyscale-friendly JPEG."""
        try:
            img = PILImage.open(io.BytesIO(raw))

            # Flatten transparency
            if img.mode in ("RGBA", "P"):
                bg = PILImage.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    bg.paste(img, mask=img.split()[3])
                else:
                    bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            if img.width > KINDLE_WIDTH_PX:
                ratio = KINDLE_WIDTH_PX / img.width
                img = img.resize(
                    (KINDLE_WIDTH_PX, int(img.height * ratio)),
                    PILImage.LANCZOS,
                )

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return buf.getvalue()
        except Exception:
            return raw   # return as-is if PIL fails

    def _register_image(self, raw: bytes, ext: str) -> str:
        """Optimise, store and return filename."""
        optimised = self._optimise(raw, ext)
        fname = _img_id(optimised)
        self._images[fname] = optimised
        return fname

    # ── Block → HTML ──────────────────────────────────────────────────────────

    def _text_html(self, b: TextBlock) -> str:
        txt = _esc(b.text().strip())
        if not txt:
            return ""
        tags = {
            "h1": f"<h1>{txt}</h1>",
            "h2": f"<h2>{txt}</h2>",
            "h3": f"<h3>{txt}</h3>",
            "caption": f'<p class="caption">{txt}</p>',
            "footnote": f'<p class="footnote">{txt}</p>',
            "body": f"<p>{txt}</p>",
        }
        return tags.get(b.level, f"<p>{txt}</p>")

    def _image_html(self, b: ImageBlock) -> str:
        if not b.data:
            return ""
        fname = self._register_image(b.data, b.ext)
        return f'<div class="figure"><img src="../images/{fname}" alt="Figure"/></div>'

    def _table_html(self, b: TableBlock) -> str:
        # Prefer rendered image fallback (more faithful to original layout)
        if b.image_data:
            fname = self._register_image(b.image_data, "png")
            return f'<div class="figure"><img src="../images/{fname}" alt="Table"/></div>'

        if not b.headers and not b.rows:
            return ""

        parts = ['<div class="table-wrap"><table>']
        if b.headers:
            parts.append("<thead><tr>")
            for h in b.headers:
                parts.append(f"<th>{_esc(h)}</th>")
            parts.append("</tr></thead>")
        if b.rows:
            parts.append("<tbody>")
            for row in b.rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append(f"<td>{_esc(cell)}</td>")
                parts.append("</tr>")
            parts.append("</tbody>")
        parts.append("</table></div>")
        return "".join(parts)

    def _block_html(self, b: Block) -> str:
        if isinstance(b, TextBlock):
            return self._text_html(b)
        if isinstance(b, ImageBlock):
            return self._image_html(b)
        if isinstance(b, TableBlock):
            return self._table_html(b)
        return ""

    # ── Page / chapter assembly ────────────────────────────────────────────────

    def _page_html(self, page: ParsedPage) -> str:
        parts = []
        for b in page.blocks:
            h = self._block_html(b)
            if h:
                parts.append(h)
        return "\n".join(parts)

    def _chapter_xhtml(self, body: str) -> str:
        title = _esc(self.doc.title)
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">\n'
            "<head>\n"
            '  <meta charset="utf-8"/>\n'
            f"  <title>{title}</title>\n"
            '  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>\n'
            "</head>\n"
            "<body>\n"
            f"{body}\n"
            "</body>\n"
            "</html>"
        )

    # ── OPF / NCX ─────────────────────────────────────────────────────────────

    def _opf(self, chapters: List[str]) -> str:
        items = []
        for i, ch in enumerate(chapters):
            items.append(
                f'<item id="ch{i}" href="text/{ch}" '
                f'media-type="application/xhtml+xml"/>'
            )
        for fname in self._images:
            items.append(
                f'<item id="{fname}" href="images/{fname}" media-type="image/jpeg"/>'
            )
        items.append('<item id="css" href="styles/style.css" media-type="text/css"/>')
        items.append(
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        )
        spine = "".join(f'<itemref idref="ch{i}"/>' for i in range(len(chapters)))
        title = _esc(self.doc.title)
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<package version="2.0" xmlns="http://www.idpf.org/2007/opf" '
            f'unique-identifier="uid">\n'
            "  <metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\"\n"
            '            xmlns:opf="http://www.idpf.org/2007/opf">\n'
            f"    <dc:title>{title}</dc:title>\n"
            "    <dc:language>en</dc:language>\n"
            f'    <dc:identifier id="uid">urn:uuid:{self._uid}</dc:identifier>\n'
            "  </metadata>\n"
            "  <manifest>\n"
            + "".join(f"    {i}\n" for i in items)
            + "  </manifest>\n"
            f"  <spine toc=\"ncx\">{spine}</spine>\n"
            "</package>"
        )

    def _ncx(self, chapters: List[str]) -> str:
        nav = "".join(
            f'<navPoint id="n{i}" playOrder="{i + 1}">'
            f"<navLabel><text>Page {i + 1}</text></navLabel>"
            f'<content src="text/{ch}"/></navPoint>'
            for i, ch in enumerate(chapters)
        )
        title = _esc(self.doc.title)
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" '
            '"http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            "  <head>\n"
            f'    <meta name="dtb:uid" content="urn:uuid:{self._uid}"/>\n'
            '    <meta name="dtb:depth" content="1"/>\n'
            "  </head>\n"
            f"  <docTitle><text>{title}</text></docTitle>\n"
            f"  <navMap>{nav}</navMap>\n"
            "</ncx>"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def build(self, output_path: str) -> str:
        # All pages merged into a single flowing chapter
        all_html = "\n".join(
            self._page_html(p) for p in self.doc.pages
        )
        chapters = ["chapter.xhtml"]
        chapter_xhtml = self._chapter_xhtml(all_html)

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as epub:
            # mimetype must be first and uncompressed
            epub.writestr(
                zipfile.ZipInfo("mimetype"),
                "application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            epub.writestr("META-INF/container.xml", CONTAINER_XML)
            epub.writestr("OEBPS/styles/style.css", CSS)
            epub.writestr("OEBPS/text/chapter.xhtml", chapter_xhtml)
            for fname, img_bytes in self._images.items():
                epub.writestr(f"OEBPS/images/{fname}", img_bytes)
            epub.writestr("OEBPS/content.opf", self._opf(chapters))
            epub.writestr("OEBPS/toc.ncx", self._ncx(chapters))

        return output_path
