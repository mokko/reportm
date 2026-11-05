"""
render - turn a bundle into a PDF.

No network and no MpApi here: the bundle already holds the module XML and the
image files, so a report can be rebuilt as often as wanted, offline.

One object per page: heading, metadata table, then its photos in a grid sized to
whatever room is left on the page.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape

from lxml import etree
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from reportm.bundle import Bundle
from reportm.fields import NSMAP, ReportConfig, resolve

MARGIN = 1.8 * cm
GAP = 0.25 * cm
# A flowable that is exactly as tall as the room left does not fit: reportlab's
# float arithmetic tips it over and the whole grid moves to the next page. Give
# the fit a few points of slack.
FIT_SLACK = 4.0
COVER_ID = "cover"
BODY_ID = "body"


@dataclass
class ObjectPage:
    item_id: str
    heading: str
    rows: list[tuple[str, str]] = dc_field(default_factory=list)
    images: list[Path] = dc_field(default_factory=list)


@dataclass
class BuildResult:
    path: Path
    objects: int
    images: int
    skipped: int
    without_image: int


#
# images
#


def scale_image(src: Path, dst_dir: Path, max_edge: int) -> Path | None:
    """Write a report-sized JPEG copy of src into dst_dir, or None if src is
    not an image Pillow can read.

    Orientation is applied from EXIF first, otherwise portrait photos come out
    sideways; CMYK and 16-bit TIFFs are converted, otherwise JPEG saving fails.
    """
    from PIL import Image as PILImage, ImageOps

    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{src.stem}-{max_edge}.jpg"
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst

    try:
        with PILImage.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.thumbnail((max_edge, max_edge), PILImage.Resampling.LANCZOS)
            im.save(dst, "JPEG", quality=85, optimize=True)
    except Exception:
        return None
    return dst


def _intrinsic_size(path: Path) -> tuple[float, float]:
    return ImageReader(str(path)).getSize()


def _fit(path: Path, box_w: float, box_h: float) -> tuple[float, float]:
    iw, ih = _intrinsic_size(path)
    if iw <= 0 or ih <= 0:
        return box_w, box_h
    scale = min(box_w / iw, box_h / ih)
    return iw * scale, ih * scale


def _grid_table(
    images: list[Path], avail_w: float, avail_h: float
) -> Table | None:
    """Images laid out in a grid that fits avail_w x avail_h exactly."""
    n = len(images)
    if n == 0:
        return None
    cols = 1 if n == 1 else (2 if n <= 4 else 3)
    rows = math.ceil(n / cols)
    cell_w = (avail_w - GAP * (cols - 1)) / cols
    cell_h = (avail_h - GAP * (rows - 1)) / rows
    pad = 0.15 * cm
    box_w = max(cell_w - 2 * pad, 1 * cm)
    box_h = max(cell_h - 2 * pad, 1 * cm)

    cells: list[list[object]] = []
    for r in range(rows):
        row: list[object] = []
        for c in range(cols):
            i = r * cols + c
            if i < n:
                w, h = _fit(images[i], box_w, box_h)
                row.append(Image(str(images[i]), width=w, height=h))
            else:
                row.append("")
        cells.append(row)

    t = Table(cells, colWidths=[cell_w] * cols, rowHeights=[cell_h] * rows)
    t.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), pad),
                ("RIGHTPADDING", (0, 0), (-1, -1), pad),
                ("TOPPADDING", (0, 0), (-1, -1), pad),
                ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ]
        )
    )
    return t


#
# reading the bundle
#


def _texts(node, path: str) -> list[str]:
    out: list[str] = []
    try:
        found = node.xpath(path, namespaces=NSMAP)
    except Exception:
        return out
    for n in found:
        text = n if isinstance(n, str) else "".join(n.itertext())
        text = " ".join(text.split())
        if text:
            out.append(text)
    return out


def _image_files(images_dir: Path, mul_ids: Iterable[str]) -> list[Path]:
    """Images on disk for a set of multimedia ids, in the order given.

    Keyed on the multimedia id, not on the file name: two records may well
    point at the same original file name, and one object may have several.
    """
    files: list[Path] = []
    for mul_id in mul_ids:
        hits = sorted(p for p in images_dir.glob(f"{mul_id}.*") if p.is_file())
        files.extend(hits)
    return files


def read_objects(
    bundle: Bundle,
    cfg: ReportConfig,
    *,
    max_edge: int = 1800,
    max_images: int | None = None,
) -> tuple[list[ObjectPage], int]:
    """Object pages in document order, plus the number of unreadable images.

    Images are scaled here, so that a page holds only what the report can
    actually show: the media count on the page and the grid below it then agree,
    which they do not if the count comes from the files on disk.
    """
    if not bundle.objects_xml.is_file():
        raise FileNotFoundError(f"No object data in bundle: {bundle.objects_xml}")
    objects_doc = etree.parse(str(bundle.objects_xml))

    items = objects_doc.xpath(
        "/m:application/m:modules/m:module[@name='Object']/m:moduleItem",
        namespaces=NSMAP,
    )
    if not items:
        raise ValueError(
            f"{bundle.objects_xml} contains no Object moduleItems — wrong group, "
            "or the module name in the file is not 'Object'."
        )

    skipped = 0
    pages: list[ObjectPage] = []
    for itemN in items:
        item_id = itemN.get("id", "?")
        mul_ids = itemN.xpath(
            "m:moduleReference[@name='ObjMultimediaRef']/m:moduleReferenceItem"
            "/@moduleItemId",
            namespaces=NSMAP,
        )
        images: list[Path] = []
        for src in _image_files(bundle.images_dir, mul_ids):
            scaled = scale_image(src, bundle.scaled_dir, max_edge)
            if scaled is None:
                skipped += 1
                continue
            images.append(scaled)
            if max_images is not None and len(images) >= max_images:
                break
        pages.append(
            ObjectPage(
                item_id=item_id,
                heading=_heading(itemN, item_id),
                rows=_rows(itemN, cfg, mul_count=len(images)),
                images=images,
            )
        )
    return pages, skipped


def _heading(itemN, item_id: str) -> str:
    number = _texts(itemN, "m:dataField[@name='ObjObjectNumberTxt']/m:value")
    if not number:
        number = _texts(
            itemN,
            "m:repeatableGroup[@name='ObjObjectNumberGrp']/m:repeatableGroupItem"
            "/m:dataField[@name='InventarNrSTxt']/m:value",
        )
    title = _texts(
        itemN,
        "m:repeatableGroup[@name='ObjObjectTitleGrp']/m:repeatableGroupItem"
        "/m:dataField[@name='TitleTxt']/m:value",
    )
    number_txt = number[0] if number else f"ID {item_id}"
    if title:
        return f"{number_txt} — {title[0]}"
    return number_txt


def _rows(itemN, cfg: ReportConfig, *, mul_count: int) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for f in cfg.fields:
        value = resolve(itemN, f, mul_count=mul_count)
        if value:
            rows.append((f.label, value))
    return rows


#
# the document
#


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "cover_title": ParagraphStyle(
            "cover_title", fontName="Helvetica-Bold", fontSize=24, leading=29
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta", fontName="Helvetica", fontSize=11.5, leading=17,
            textColor=colors.HexColor("#444444"),
        ),
        "heading": ParagraphStyle(
            "heading", fontName="Helvetica-Bold", fontSize=15, leading=19,
            spaceAfter=2,
        ),
        "objid": ParagraphStyle(
            "objid", fontName="Helvetica", fontSize=8.5, leading=11,
            textColor=colors.HexColor("#888888"),
        ),
        "label": ParagraphStyle(
            "label", fontName="Helvetica-Bold", fontSize=9, leading=12,
            textColor=colors.HexColor("#333333"),
        ),
        "value": ParagraphStyle("value", fontName="Helvetica", fontSize=9, leading=12),
    }


def _footer(canvas, doc, title: str) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawString(MARGIN, 1.1 * cm, title)
    canvas.drawRightString(A4[0] - MARGIN, 1.1 * cm, f"Seite {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#dddddd"))
    canvas.line(MARGIN, 1.45 * cm, A4[0] - MARGIN, 1.45 * cm)
    canvas.restoreState()


def build(
    bundle: Bundle,
    out: Path | str,
    *,
    cfg: ReportConfig | None = None,
    max_edge: int = 1800,
    max_images: int | None = None,
    title: str | None = None,
) -> BuildResult:
    """Write the PDF for a bundle and report what went in."""
    cfg = cfg or ReportConfig()
    out = Path(out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    pages, skipped = read_objects(
        bundle, cfg, max_edge=max_edge, max_images=max_images
    )
    report_title = title or cfg.title or bundle.meta.get("title") or "Objektbericht"

    total_images = sum(len(p.images) for p in pages)
    without_image = sum(1 for p in pages if not p.images)

    styles = _styles()
    frame_w = A4[0] - 2 * MARGIN
    frame_h = A4[1] - 2 * MARGIN - 0.9 * cm

    def on_page(canvas, doc):
        _footer(canvas, doc, report_title)

    doc = BaseDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=report_title,
        author=bundle.meta.get("base_url", "") or "reportm",
        creator="reportm",
    )
    frame = Frame(
        MARGIN, MARGIN, frame_w, frame_h, id="main",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id=BODY_ID, frames=[frame], onPage=on_page)])

    story: list[object] = []
    # cover
    story.append(Spacer(1, 6 * cm))
    story.append(Paragraph(escape(report_title), styles["cover_title"]))
    story.append(Spacer(1, 0.6 * cm))
    for line in _cover_lines(bundle, len(pages), total_images):
        story.append(Paragraph(escape(line), styles["cover_meta"]))
    story.append(PageBreak())

    # one page per object
    for page in pages:
        story.extend(_object_story(page, styles, frame_w, frame_h))
        story.append(PageBreak())
    if story and isinstance(story[-1], PageBreak):
        story.pop()  # no trailing blank page

    doc.build(story)
    return BuildResult(
        path=out,
        objects=len(pages),
        images=total_images,
        skipped=skipped,
        without_image=without_image,
    )


def _cover_lines(bundle: Bundle, objects: int, images: int) -> list[str]:
    from datetime import date

    lines = [f"Gruppe: {bundle.meta.get('group_id', '?')}"]
    if bundle.meta.get("base_url"):
        lines.append(f"Quelle: {bundle.meta['base_url']}")
    if bundle.meta.get("fetched"):
        lines.append(f"Datenstand: {bundle.meta['fetched']}")
    lines.append(f"Objekte: {objects}   Bilder: {images}")
    lines.append(f"Erstellt: {date.today().isoformat()} mit reportm")
    return lines


def _object_story(page: ObjectPage, styles, frame_w: float, frame_h: float) -> list:
    """Heading, metadata, and a photo grid sized to whatever room is left.

    The room is measured with wrap() rather than estimated: a grid that is one
    point too tall gets pushed onto a page of its own, which reads as a broken
    report.
    """
    story: list[object] = []
    heading = Paragraph(escape(page.heading), styles["heading"])
    objid = Paragraph(f"Modul-ID {escape(page.item_id)}", styles["objid"])
    story.extend([heading, objid])

    gap_after_head = 0.3 * cm
    story.append(Spacer(1, gap_after_head))
    used = heading.wrap(frame_w, frame_h)[1] + objid.wrap(frame_w, frame_h)[1]
    used += gap_after_head

    if page.rows:
        label_w = 4.2 * cm
        table = Table(
            [
                [
                    Paragraph(escape(label), styles["label"]),
                    Paragraph(escape(value), styles["value"]),
                ]
                for label, value in page.rows
            ],
            colWidths=[label_w, frame_w - label_w],
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#eeeeee")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        used += table.wrap(frame_w, frame_h)[1] + 0.35 * cm
        story.extend([table, Spacer(1, 0.35 * cm)])

    if page.images:
        avail_h = frame_h - used - FIT_SLACK
        if avail_h >= 3 * cm:
            grid = _grid_table(page.images, frame_w, avail_h)
            if grid is not None:
                story.append(grid)
        else:
            # metadata filled the page; the photos follow on their own page
            story.append(PageBreak())
            story.append(Spacer(1, 1 * cm))
            story.append(_grid_table(page.images, frame_w, frame_h - 1 * cm))
    else:
        story.append(
            Paragraph(
                "<i>Kein Bild vorhanden.</i>",
                ParagraphStyle("none", fontName="Helvetica-Oblique", fontSize=9,
                               textColor=colors.HexColor("#999999")),
            )
        )
    return story

