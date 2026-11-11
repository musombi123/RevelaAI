"""Deterministic DOCX/PPTX/XLSX/CSV generation and private expiring file storage."""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import hmac
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image as PILImage, ImageOps as PILImageOps, UnidentifiedImageError
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches as PptInches, Pt as PptPt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as PDFImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak


def storage_root() -> Path:
    root = Path(os.getenv("REVELAAI_PRODUCTIVITY_DIR", "/tmp/revelaai-productivity")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _signing_key() -> bytes:
    raw = os.getenv("REVELAAI_FILE_SIGNING_SECRET", "").strip() or os.getenv("JWT_SECRET", "").strip()
    if len(raw.encode("utf-8")) < 32:
        raise RuntimeError("File signing is not configured; set REVELAAI_FILE_SIGNING_SECRET.")
    return raw.encode("utf-8")


def _safe_name(value: str, suffix: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "RevelaAI-export")).strip(".-_")[:70] or "RevelaAI-export"
    return name + suffix


def _write_artifact(owner_id: str, content: bytes, filename: str, mime: str,
                    *, preview: Any = None, retention_seconds: int = 86400) -> dict[str, Any]:
    if not owner_id or len(owner_id) > 160:
        raise ValueError("Authenticated user identity is required.")
    file_id = uuid.uuid4().hex
    owner_folder = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:24]
    folder = storage_root() / owner_folder
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / file_id
    target.write_bytes(content)
    expires = int(time.time()) + max(300, min(retention_seconds, 7 * 86400))
    meta = {
        "file_id": file_id, "filename": filename, "mime_type": mime,
        "owner_hash": owner_folder, "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires, "size_bytes": len(content),
    }
    (folder / (file_id + ".json")).write_text(json.dumps(meta), encoding="utf-8")
    signature = hmac.new(_signing_key(), f"{file_id}:{expires}".encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"/api/productivity/files/{file_id}?expires={expires}&sig={signature}"
    return {"file_id": file_id, "filename": filename, "mime_type": mime,
            "size_bytes": len(content), "expires_at": expires, "download_url": url,
            "preview": preview}


def read_signed_file(file_id: str, expires: int, signature: str) -> tuple[Path, dict[str, Any]]:
    if not re.fullmatch(r"[a-f0-9]{32}", str(file_id or "")):
        raise FileNotFoundError("File not found.")
    if int(expires) < int(time.time()):
        raise PermissionError("Download link expired.")
    expected = hmac.new(_signing_key(), f"{file_id}:{int(expires)}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(signature or "")):
        raise PermissionError("Download link is invalid.")
    for folder in storage_root().iterdir():
        if not folder.is_dir():
            continue
        meta_path = folder / (file_id + ".json")
        target = folder / file_id
        if meta_path.is_file() and target.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if int(meta.get("expires_at", 0)) < int(time.time()) or int(meta.get("expires_at", 0)) != int(expires):
                raise PermissionError("File has expired.")
            return target, meta
    raise FileNotFoundError("File not found.")


def _preview_pdf(
    owner_id: str,
    title: str,
    blocks: list[dict[str, Any]],
    kind: str,
    *,
    images: list[dict[str, Any]] | None = None,
    official_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stream = io.BytesIO()
    page = landscape(A4) if kind == "slides" else A4
    doc = SimpleDocTemplate(stream, pagesize=page, rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    story = []
    images = images or []
    metadata = official_metadata if isinstance(official_metadata, dict) else {}
    for item in images:
        if item["placement"] in {"header", "cover", "title_slide", "all_slides"}:
            story.extend([
                PDFImage(io.BytesIO(item["content"]), width=min(item["width_inches"] * 72, 180), height=min(item["width_inches"] * 72 * item["height"] / item["width"], 100), kind="proportional"),
                Spacer(1, 3*mm),
            ])
    if kind == "document" and metadata:
        for label, key in (("Date", "date"), ("Our reference", "reference"), ("To", "recipient"),
                           ("Organization", "recipient_organization"), ("From", "sender")):
            value = metadata.get(key)
            if value:
                story.append(Paragraph(f"<b>{escape(label)}:</b> {escape(str(value)[:240])}", styles["BodyText"]))
        address = metadata.get("recipient_address") or []
        if isinstance(address, str):
            address = [address]
        for line in address[:5] if isinstance(address, list) else []:
            story.append(Paragraph(escape(str(line)[:240]), styles["BodyText"]))
        if metadata.get("subject"):
            story.extend([Spacer(1, 3*mm), Paragraph("<b>RE: " + escape(str(metadata["subject"]).upper()[:240]) + "</b>", styles["BodyText"]), Spacer(1, 3*mm)])
        if metadata.get("salutation"):
            story.extend([Paragraph(escape(str(metadata["salutation"])[:180]), styles["BodyText"]), Spacer(1, 2*mm)])
    if title and (kind == "slides" or not metadata):
        story.extend([Paragraph(escape(title[:180]), styles["Title"]), Spacer(1, 8*mm)])
    if kind == "slides":
        for index, item in enumerate(blocks, 1):
            story.append(Paragraph(f"Slide {index}: {escape(str(item.get('title') or 'Untitled'))}", styles["Heading1"]))
            for bullet in (item.get("bullets") or [])[:12]:
                story.append(Paragraph("• " + escape(str(bullet)), styles["BodyText"]))
            story.append(Spacer(1, 12*mm))
    else:
        for section_index, item in enumerate(blocks):
            for image_item in images:
                if image_item["placement"] == "inline" and image_item["section_index"] == section_index and image_item["paragraph_index"] < 0:
                    story.append(PDFImage(io.BytesIO(image_item["content"]), width=min(image_item["width_inches"] * 72, 420), kind="proportional"))
                    story.append(Spacer(1, 2*mm))
            if item.get("heading"):
                story.append(Paragraph(escape(str(item["heading"])), styles["Heading2"]))
            paragraphs = (item.get("paragraphs") or [])[:40]
            for paragraph_index, paragraph in enumerate(paragraphs):
                story.append(Paragraph(escape(str(paragraph)), styles["BodyText"]))
                story.append(Spacer(1, 2*mm))
                for image_item in images:
                    if image_item["placement"] == "inline" and image_item["section_index"] == section_index and image_item["paragraph_index"] == paragraph_index:
                        story.append(PDFImage(io.BytesIO(image_item["content"]), width=min(image_item["width_inches"] * 72, 420), kind="proportional"))
                        story.append(Spacer(1, 2*mm))
            for table_data in (item.get("tables") or [])[:4]:
                rows = table_data.get("rows") or []
                headers = table_data.get("headers") or []
                data = [[str(x)[:120] for x in headers]] + [[str(x)[:120] for x in row] for row in rows[:100]]
                if data and data[0]:
                    table = Table(data, repeatRows=1)
                    table.setStyle(TableStyle([
                        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#10243A")),
                        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
                        ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#D6DCE5")),
                        ("VALIGN",(0,0),(-1,-1),"TOP"),
                        ("FONTSIZE",(0,0),(-1,-1),7),
                        ("BOTTOMPADDING",(0,0),(-1,-1),5),
                    ]))
                    story.extend([table, Spacer(1, 5*mm)])
        if metadata:
            if metadata.get("closing"):
                story.extend([Spacer(1, 3*mm), Paragraph(escape(str(metadata["closing"])[:180]), styles["BodyText"])])
            if metadata.get("signatory"):
                story.extend([Spacer(1, 12*mm), Paragraph("<b>" + escape(str(metadata["signatory"])[:180]) + "</b>", styles["BodyText"])])
            if metadata.get("signatory_title"):
                story.append(Paragraph(escape(str(metadata["signatory_title"])[:180]), styles["BodyText"]))
            for label, key in (("Enclosures", "enclosures"), ("Cc", "cc")):
                values = metadata.get(key)
                if isinstance(values, str):
                    values = [values]
                if isinstance(values, list) and values:
                    story.append(Paragraph(f"<b>{label}:</b> " + escape("; ".join(str(v)[:160] for v in values[:12])), styles["BodyText"]))
    doc.build(story)
    return _write_artifact(owner_id, stream.getvalue(), _safe_name(title, ".pdf"), "application/pdf",
                           preview={"type":"pdf","pages":"rendered","images_embedded":len(images)}, retention_seconds=86400)


def create_spreadsheet(owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "RevelaAI Spreadsheet").strip()[:160]
    sheets = payload.get("sheets")
    if not isinstance(sheets, list) or not sheets or len(sheets) > 20:
        raise ValueError("Provide between 1 and 20 worksheet definitions.")
    wb = Workbook()
    wb.remove(wb.active)
    previews = []
    for index, definition in enumerate(sheets):
        if not isinstance(definition, dict):
            raise ValueError("Each worksheet must be an object.")
        name = re.sub(r"[\\/*?:\[\]]", "", str(definition.get("name") or f"Sheet {index+1}"))[:31] or f"Sheet{index+1}"
        ws = wb.create_sheet(name)
        headers = definition.get("headers") or []
        rows = definition.get("rows") or []
        if not isinstance(headers, list) or len(headers) > 80 or not isinstance(rows, list) or len(rows) > 5000:
            raise ValueError("A worksheet may contain at most 80 columns and 5,000 rows.")
        if headers:
            ws.append([str(x)[:200] for x in headers])
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="10243A")
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        for row in rows:
            values = list(row.values()) if isinstance(row, dict) else row
            if not isinstance(values, list) or len(values) > 80:
                raise ValueError("Every spreadsheet row must be an array or object with at most 80 values.")
            clean = []
            for value in values:
                if isinstance(value, str) and value.startswith("="):
                    if len(value) > 250 or not re.fullmatch(r"=[A-Z0-9_.$():,+*/ -]+", value.upper()) or re.search(r"\[[^]]+\]|!|WEBSERVICE|HYPERLINK|DDE|INDIRECT|OFFSET", value, re.I):
                        raise ValueError("Only simple, local spreadsheet formulas are allowed.")
                clean.append(value if isinstance(value, (str, int, float, bool)) or value is None else str(value)[:1000])
            ws.append(clean)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in range(1, min(ws.max_column, 40)+1):
            letter = get_column_letter(col)
            longest = max([len(str(ws.cell(r,col).value or "")) for r in range(1, min(ws.max_row,100)+1)] or [10])
            ws.column_dimensions[letter].width = min(42, max(12, longest + 2))
        data_preview = [[ws.cell(r,c).value for c in range(1, min(ws.max_column,12)+1)] for r in range(1,min(ws.max_row,31)+1)]
        previews.append({"sheet":name,"rows":data_preview,"truncated":ws.max_row>30 or ws.max_column>12})
    from io import BytesIO
    stream=BytesIO(); wb.save(stream)
    artifact=_write_artifact(owner_id,stream.getvalue(),_safe_name(title,".xlsx"),"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",preview={"type":"table","sheets":previews},retention_seconds=86400)
    artifact["kind"]="spreadsheet"
    return artifact


def create_word_document(owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "RevelaAI Document").strip()[:180]
    blocks = payload.get("sections")
    if not isinstance(blocks, list) or len(blocks) > 80:
        raise ValueError("Provide up to 80 document sections.")
    images = _decode_document_images(payload.get("images"), allowed_placements={"header", "cover", "inline"})
    metadata = payload.get("official_metadata") if isinstance(payload.get("official_metadata"), dict) else {}
    official = str(payload.get("document_style") or "standard").lower() == "official"
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.9)
    section.right_margin = Inches(0.9)
    document.core_properties.title = title
    document.core_properties.author = str(metadata.get("organization") or metadata.get("organisation") or "RevelaAI")[:180]

    for item in images:
        if item["placement"] == "header":
            paragraph = section.header.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            shape = paragraph.add_run().add_picture(io.BytesIO(item["content"]), width=Inches(item["width_inches"]))
            shape._inline.docPr.set("descr", item["alt_text"])
        elif item["placement"] == "cover":
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            shape = paragraph.add_run().add_picture(io.BytesIO(item["content"]), width=Inches(item["width_inches"]))
            shape._inline.docPr.set("descr", item["alt_text"])
            paragraph.paragraph_format.space_after = Pt(10)

    if official:
        _add_official_metadata_to_docx(document, metadata)
    elif title:
        document.add_heading(title, 0)

    for section_index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        heading = str(block.get("heading") or "").strip()
        if heading:
            document.add_heading(heading[:180], level=max(1, min(3, int(block.get("level", 1) or 1))))
        paragraphs = (block.get("paragraphs") or [])[:40]
        for paragraph_index, paragraph_text in enumerate(paragraphs):
            paragraph = document.add_paragraph(str(paragraph_text)[:12000])
            paragraph.paragraph_format.space_after = Pt(7)
            for item in images:
                if item["placement"] == "inline" and item["section_index"] == section_index and item["paragraph_index"] == paragraph_index:
                    image_paragraph = document.add_paragraph()
                    shape = image_paragraph.add_run().add_picture(io.BytesIO(item["content"]), width=Inches(item["width_inches"]))
                    shape._inline.docPr.set("descr", item["alt_text"])
        for item in images:
            if item["placement"] == "inline" and item["section_index"] == section_index and item["paragraph_index"] < 0:
                image_paragraph = document.add_paragraph()
                shape = image_paragraph.add_run().add_picture(io.BytesIO(item["content"]), width=Inches(item["width_inches"]))
                shape._inline.docPr.set("descr", item["alt_text"])
        for table_data in (block.get("tables") or [])[:4]:
            headers = table_data.get("headers") or []
            rows = table_data.get("rows") or []
            if headers and len(headers) <= 20 and len(rows) <= 500:
                table = document.add_table(rows=1, cols=len(headers))
                table.style = "Light Shading Accent 1"
                for i, header in enumerate(headers):
                    table.rows[0].cells[i].text = str(header)[:200]
                for row in rows:
                    cells = table.add_row().cells
                    for i, value in enumerate(row[:len(headers)]):
                        cells[i].text = str(value)[:1000]
    if official:
        _add_official_closing_to_docx(document, metadata)

    stream = io.BytesIO()
    document.save(stream)
    primary = _write_artifact(
        owner_id, stream.getvalue(), _safe_name(title, ".docx"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        preview={"type":"document","title":title,"sections":blocks[:10],"images_embedded":len(images),"document_style":"official" if official else "standard"},
        retention_seconds=86400,
    )
    pdf = _preview_pdf(owner_id, title, blocks, "document", images=images, official_metadata=metadata if official else None)
    return {"kind":"word","files":[primary,pdf],"primary":primary,"preview_file":pdf,
            "preview":{"type":"document","title":title,"sections":blocks[:10],"images_embedded":len(images),
                       "document_style":"official" if official else "standard"}}


def create_powerpoint(owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "RevelaAI Presentation").strip()[:180]
    slides = payload.get("slides")
    if not isinstance(slides, list) or not slides or len(slides) > 80:
        raise ValueError("Provide between 1 and 80 slides.")
    images = _decode_document_images(payload.get("images"), allowed_placements={"title_slide", "slide", "all_slides"})
    prs = Presentation()
    prs.core_properties.title = title
    prs.core_properties.author = "RevelaAI"
    prs.slide_width = PptInches(13.333)
    prs.slide_height = PptInches(7.5)
    for index, item in enumerate(slides):
        if not isinstance(item, dict):
            continue
        layout = prs.slide_layouts[0] if index == 0 else prs.slide_layouts[1]
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = str(item.get("title") or (title if index == 0 else f"Slide {index+1}"))[:180]
        if index == 0 and len(slide.placeholders) > 1:
            slide.placeholders[1].text = str(item.get("subtitle") or "Created with RevelaAI")[:250]
        else:
            placeholder = next((p for p in slide.placeholders if p.placeholder_format.idx == 1), None)
            if placeholder:
                text_frame = placeholder.text_frame
                text_frame.clear()
                for bullet_index, text_value in enumerate((item.get("bullets") or [])[:12]):
                    paragraph = text_frame.paragraphs[0] if bullet_index == 0 else text_frame.add_paragraph()
                    paragraph.text = str(text_value)[:500]
                    paragraph.level = 0
                    paragraph.font.size = PptPt(24)
    for item in images:
        if item["placement"] == "all_slides":
            target_slides = list(prs.slides)
        else:
            index = 0 if item["placement"] == "title_slide" else item["slide_index"]
            if index < 0 or index >= len(prs.slides):
                raise ValueError("An embedded presentation image refers to a slide that does not exist.")
            target_slides = [prs.slides[index]]
        for slide in target_slides:
            width = item["width_inches"]
            max_left = max(0.0, 13.333 - width)
            left = min(max(0.0, item["x_inches"]), max_left)
            top = min(max(0.0, item["y_inches"]), 7.1)
            slide.shapes.add_picture(io.BytesIO(item["content"]), PptInches(left), PptInches(top), width=PptInches(width))

    stream = io.BytesIO()
    prs.save(stream)
    primary = _write_artifact(
        owner_id, stream.getvalue(), _safe_name(title, ".pptx"),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        preview={"type":"slides","slides":slides[:12],"images_embedded":len(images)},
        retention_seconds=86400,
    )
    pdf = _preview_pdf(owner_id, title, slides, "slides", images=images)
    return {"kind":"powerpoint","files":[primary,pdf],"primary":primary,"preview_file":pdf,
            "preview":{"type":"slides","slides":slides[:12],"images_embedded":len(images)}}


def create_csv(owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    rows=payload.get("rows")
    headers=payload.get("headers") or []
    if not isinstance(rows,list) or len(rows)>10000 or len(headers)>100:
        raise ValueError("CSV supports up to 10,000 rows and 100 columns.")
    from io import StringIO
    stream=StringIO(); writer=csv.writer(stream); writer.writerow(headers)
    for row in rows:
        if not isinstance(row,list) or len(row)>100: raise ValueError("Invalid CSV row.")
        writer.writerow([str(x)[:4000] if x is not None else "" for x in row])
    return _write_artifact(owner_id,stream.getvalue().encode("utf-8-sig"),_safe_name(str(payload.get("title") or "RevelaAI-data"),".csv"),"text/csv",preview={"type":"table","headers":headers,"rows":rows[:30]},retention_seconds=86400)
