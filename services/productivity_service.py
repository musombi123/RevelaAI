"""Deterministic DOCX/PPTX/XLSX/CSV generation and private expiring file storage."""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak


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


def _preview_pdf(owner_id: str, title: str, blocks: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    from io import BytesIO
    stream = BytesIO()
    page = landscape(A4) if kind == "slides" else A4
    doc = SimpleDocTemplate(stream, pagesize=page, rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(title[:180]), styles["Title"]), Spacer(1, 8*mm)]
    if kind == "slides":
        for index, item in enumerate(blocks, 1):
            story.append(Paragraph(f"Slide {index}: {escape(str(item.get('title') or 'Untitled'))}", styles["Heading1"]))
            for bullet in (item.get("bullets") or [])[:12]:
                story.append(Paragraph("• " + escape(str(bullet)), styles["BodyText"]))
            story.append(Spacer(1, 12*mm))
    else:
        for item in blocks:
            if item.get("heading"):
                story.append(Paragraph(escape(str(item["heading"])), styles["Heading2"]))
            for paragraph in (item.get("paragraphs") or [])[:30]:
                story.append(Paragraph(escape(str(paragraph)), styles["BodyText"]))
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
    doc.build(story)
    return _write_artifact(owner_id, stream.getvalue(), _safe_name(title, ".pdf"), "application/pdf",
                           preview={"type":"pdf","pages":"rendered"}, retention_seconds=86400)



def _decode_document_images(images: Any, *, allowed_placements: set[str]) -> list[dict[str, Any]]:
    """Validate user-provided images and normalize them to PNG bytes for Office/PDF embeds."""
    if images is None:
        return []
    if not isinstance(images, list) or len(images) > 8:
        raise ValueError("Provide no more than 8 embedded images.")
    decoded: list[dict[str, Any]] = []
    total_bytes = 0
    for index, item in enumerate(images):
        if not isinstance(item, dict):
            raise ValueError("Each embedded image must be an object.")
        encoded = str(item.get("image_base64") or item.get("data") or "").strip()
        mime = str(item.get("mime_type") or item.get("mimeType") or "").strip().lower()
        if encoded.startswith("data:"):
            header, separator, encoded = encoded.partition(",")
            if not separator or ";base64" not in header.lower():
                raise ValueError(f"Embedded image {index + 1} must be a base64 data URL.")
            declared = header[5:].split(";", 1)[0].lower()
            if mime and mime != declared:
                raise ValueError(f"Embedded image {index + 1} MIME type does not match its data URL.")
            mime = declared
        if not encoded or len(encoded) > ((4 * 1024 * 1024 + 2) // 3) * 4 + 8:
            raise ValueError(f"Embedded image {index + 1} must be non-empty and no larger than 4 MB.")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Embedded image {index + 1} is not valid base64.") from exc
        total_bytes += len(raw)
        if not raw or len(raw) > 4 * 1024 * 1024 or total_bytes > 8 * 1024 * 1024:
            raise ValueError("Embedded images may total no more than 8 MB.")
        try:
            with PILImage.open(io.BytesIO(raw)) as source:
                actual_format = str(source.format or "").upper()
                actual_mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}.get(actual_format)
                if actual_mime is None or (mime and mime != actual_mime):
                    raise ValueError(f"Embedded image {index + 1} must be a valid PNG, JPEG or WEBP image with a matching MIME type.")
                if source.width < 1 or source.height < 1 or source.width * source.height > 20_000_000:
                    raise ValueError(f"Embedded image {index + 1} dimensions exceed the 20-megapixel limit.")
                source.verify()
            with PILImage.open(io.BytesIO(raw)) as source:
                normalized = PILImageOps.exif_transpose(source)
                normalized = normalized.convert("RGBA" if "A" in normalized.getbands() else "RGB")
                png = io.BytesIO()
                normalized.save(png, format="PNG", optimize=True)
                width, height = normalized.size
        except (UnidentifiedImageError, OSError, PILImage.DecompressionBombError) as exc:
            raise ValueError(f"Embedded image {index + 1} is invalid or unsupported.") from exc

        placement = str(item.get("placement") or "header").strip().lower()
        if placement not in allowed_placements:
            raise ValueError(f"Embedded image placement must be one of: {', '.join(sorted(allowed_placements))}.")
        try:
            width_inches = float(item.get("width_inches", 1.45))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Embedded image {index + 1} width must be numeric.") from exc
        if not 0.35 <= width_inches <= 6.5:
            raise ValueError(f"Embedded image {index + 1} width must be between 0.35 and 6.5 inches.")
        decoded.append({
            "content": png.getvalue(),
            "width": width,
            "height": height,
            "width_inches": width_inches,
            "placement": placement,
            "alt_text": str(item.get("alt_text") or item.get("alt") or "User-provided image")[:200],
            "section_index": int(item.get("section_index", 0) or 0),
            "paragraph_index": int(item.get("paragraph_index", -1) if item.get("paragraph_index") is not None else -1),
            "slide_index": int(item.get("slide_index", 0) or 0),
            "x_inches": float(item.get("x_inches", 10.9)),
            "y_inches": float(item.get("y_inches", 0.35)),
        })
    return decoded


def _add_official_metadata_to_docx(document: Document, metadata: dict[str, Any]) -> None:
    """Lay out supplied letter/memo particulars without inventing missing fields."""
    document_type = str(metadata.get("document_type") or "letter").strip().lower()
    org = str(metadata.get("organization") or metadata.get("organisation") or "").strip()
    org_address = metadata.get("organization_address") or metadata.get("organisation_address") or []
    if isinstance(org_address, str):
        org_address = [org_address]
    if org:
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(org[:180])
        run.bold = True
        run.font.size = Pt(14)
    for line in org_address[:4] if isinstance(org_address, list) else []:
        p = document.add_paragraph(str(line)[:240])
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if metadata.get("date"):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.add_run(str(metadata["date"])[:80])
    if metadata.get("reference"):
        p = document.add_paragraph()
        p.add_run("Our reference: ").bold = True
        p.add_run(str(metadata["reference"])[:120])
    if document_type == "memo":
        for label, key in (("To", "recipient"), ("From", "sender"), ("Date", "date"), ("Subject", "subject")):
            value = metadata.get(key)
            if value:
                p = document.add_paragraph()
                p.add_run(label + ": ").bold = True
                p.add_run(str(value)[:240])
        return
    recipient = str(metadata.get("recipient") or "").strip()
    recipient_org = str(metadata.get("recipient_organization") or "").strip()
    recipient_address = metadata.get("recipient_address") or []
    if isinstance(recipient_address, str):
        recipient_address = [recipient_address]
    for value in [recipient, recipient_org] + (recipient_address[:5] if isinstance(recipient_address, list) else []):
        if str(value or "").strip():
            document.add_paragraph(str(value)[:240])
    if metadata.get("subject"):
        p = document.add_paragraph()
        p.paragraph_format.space_before = Pt(7)
        p.paragraph_format.space_after = Pt(8)
        run = p.add_run("RE: " + str(metadata["subject"]).strip().upper()[:240])
        run.bold = True
    if metadata.get("salutation"):
        document.add_paragraph(str(metadata["salutation"])[:180])


def _add_official_closing_to_docx(document: Document, metadata: dict[str, Any]) -> None:
    closing = str(metadata.get("closing") or "").strip()
    if closing:
        document.add_paragraph(closing[:180])
    signatory = str(metadata.get("signatory") or "").strip()
    if signatory:
        p = document.add_paragraph()
        p.paragraph_format.space_before = Pt(18)
        p.add_run(signatory[:180]).bold = True
    designation = str(metadata.get("signatory_title") or "").strip()
    if designation:
        document.add_paragraph(designation[:180])
    for label, key in (("Enclosures", "enclosures"), ("Cc", "cc")):
        values = metadata.get(key)
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list) and values:
            p = document.add_paragraph()
            p.add_run(label + ": ").bold = True
            p.add_run("; ".join(str(value)[:160] for value in values[:12]))


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
    title=str(payload.get("title") or "RevelaAI Document").strip()[:180]
    blocks=payload.get("sections")
    if not isinstance(blocks,list) or len(blocks)>80: raise ValueError("Provide up to 80 document sections.")
    document=Document()
    section=document.sections[0]
    section.top_margin=Inches(0.75); section.bottom_margin=Inches(0.75)
    document.core_properties.title=title
    document.core_properties.author="RevelaAI"
    document.add_heading(title,0)
    for block in blocks:
        if not isinstance(block,dict): continue
        heading=str(block.get("heading") or "").strip()
        if heading: document.add_heading(heading[:180],level=max(1,min(3,int(block.get("level",1) or 1))))
        for paragraph in (block.get("paragraphs") or [])[:40]:
            p=document.add_paragraph(str(paragraph)[:12000])
            p.paragraph_format.space_after=Pt(7)
        for table_data in (block.get("tables") or [])[:4]:
            headers=table_data.get("headers") or []; rows=table_data.get("rows") or []
            if headers and len(headers)<=20 and len(rows)<=500:
                table=document.add_table(rows=1,cols=len(headers)); table.style="Light Shading Accent 1"
                for i,h in enumerate(headers): table.rows[0].cells[i].text=str(h)[:200]
                for row in rows:
                    cells=table.add_row().cells
                    for i,value in enumerate(row[:len(headers)]): cells[i].text=str(value)[:1000]
    from io import BytesIO
    stream=BytesIO(); document.save(stream)
    primary=_write_artifact(owner_id,stream.getvalue(),_safe_name(title,".docx"),"application/vnd.openxmlformats-officedocument.wordprocessingml.document",preview={"type":"document","title":title,"sections":blocks[:10]},retention_seconds=86400)
    pdf=_preview_pdf(owner_id,title,blocks,"document")
    return {"kind":"word","files":[primary,pdf],"primary":primary,"preview_file":pdf,"preview":{"type":"document","title":title,"sections":blocks[:10]}}


def create_powerpoint(owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    title=str(payload.get("title") or "RevelaAI Presentation").strip()[:180]
    slides=payload.get("slides")
    if not isinstance(slides,list) or not slides or len(slides)>80: raise ValueError("Provide between 1 and 80 slides.")
    prs=Presentation(); prs.core_properties.title=title; prs.core_properties.author="RevelaAI"
    prs.slide_width=PptInches(13.333); prs.slide_height=PptInches(7.5)
    for index,item in enumerate(slides):
        if not isinstance(item,dict): continue
        layout=prs.slide_layouts[0] if index==0 else prs.slide_layouts[1]
        slide=prs.slides.add_slide(layout)
        slide.shapes.title.text=str(item.get("title") or (title if index==0 else f"Slide {index+1}"))[:180]
        if index==0 and len(slide.placeholders)>1:
            slide.placeholders[1].text=str(item.get("subtitle") or "Created with RevelaAI")[:250]
        else:
            placeholder=next((p for p in slide.placeholders if p.placeholder_format.idx==1),None)
            if placeholder:
                tf=placeholder.text_frame; tf.clear()
                for bullet_index,text_value in enumerate((item.get("bullets") or [])[:12]):
                    para=tf.paragraphs[0] if bullet_index==0 else tf.add_paragraph()
                    para.text=str(text_value)[:500]; para.level=0; para.font.size=PptPt(24)
    from io import BytesIO
    stream=BytesIO(); prs.save(stream)
    primary=_write_artifact(owner_id,stream.getvalue(),_safe_name(title,".pptx"),"application/vnd.openxmlformats-officedocument.presentationml.presentation",preview={"type":"slides","slides":slides[:12]},retention_seconds=86400)
    pdf=_preview_pdf(owner_id,title,slides,"slides")
    return {"kind":"powerpoint","files":[primary,pdf],"primary":primary,"preview_file":pdf,"preview":{"type":"slides","slides":slides[:12]}}


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
