"""Generate verifiable compliance-readiness PDFs, never pretend to issue certifications.

The emitted artifact is a draft evidence/readiness report. CE/UL/ISO/RoHS/FCC are
review domains, not credentials the software can grant. A qualified authority or
accredited lab must issue any actual regulated certification.
"""
from __future__ import annotations

import hashlib
import json
import textwrap
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SUPPORTED_REPORT_KINDS = {
    "CE": "EU product conformity readiness",
    "UL": "UL / North-American product-safety evidence readiness",
    "ISO9001": "ISO 9001 quality-management evidence readiness",
    "ROHS": "RoHS restricted-substance evidence readiness",
    "FCC": "FCC / US radio-frequency emissions evidence readiness",
}
DRAFT_WARNING = (
    "DRAFT READINESS REPORT — NOT A CERTIFICATE. This software does not issue CE, UL, ISO 9001, "
    "RoHS or FCC certification and does not determine legal conformity. No authority, accredited "
    "laboratory, verified test result, or product approval is implied."
)


def canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_compliance_readiness_pdf(
    report: dict[str, Any],
    *,
    verification_url: str,
) -> bytes:
    kind = str(report.get("report_kind") or "").upper()
    if kind not in SUPPORTED_REPORT_KINDS:
        raise ValueError("Unsupported report kind.")
    if not verification_url.startswith(("https://", "http://")) or len(verification_url) > 2048:
        raise ValueError("A valid report-verification URL is required.")

    output = BytesIO()
    page_width, page_height = A4
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    pdf.setTitle(f"Draft compliance readiness — {kind}")
    pdf.setAuthor("RevelaCode")
    pdf.setSubject("Draft evidence/readiness report; not a certification")

    margin = 48
    y = page_height - 50
    pdf.setFillColor(colors.HexColor("#12304A"))
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(margin, y, "RevelaCode Compliance Evidence")
    y -= 26
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(margin, y, f"{kind} — {SUPPORTED_REPORT_KINDS[kind]}")
    y -= 22

    # High-contrast warning near the top, repeated on every page.
    pdf.setFillColor(colors.HexColor("#8D1A1A"))
    pdf.setFont("Helvetica-Bold", 10)
    for line in textwrap.wrap(DRAFT_WARNING, width=94):
        pdf.drawString(margin, y, line)
        y -= 14
    pdf.setFillColor(colors.black)
    y -= 10

    fields = [
        ("Report ID", str(report.get("report_id") or "")),
        ("Owner", str(report.get("owner_user_id") or "")),
        ("Country", str(report.get("country") or "KE")),
        ("Status", "draft_readiness_report"),
        ("Generated at (UTC)", str(report.get("created_at") or "")),
        ("Evidence completeness", "Unverified — independent evidence review required"),
    ]
    pdf.setFont("Helvetica-Bold", 10)
    for label, value in fields:
        pdf.drawString(margin, y, f"{label}:")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(margin + 145, y, value[:95])
        pdf.setFont("Helvetica-Bold", 10)
        y -= 17

    y -= 8
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(margin, y, "Product / system scope")
    y -= 17
    pdf.setFont("Helvetica", 9)
    scope = str(report.get("scope") or "No product scope was provided.")
    for line in textwrap.wrap(scope, width=106) or ["No product scope was provided."]:
        if y < 105:
            pdf.showPage()
            y = page_height - 60
            pdf.setFont("Helvetica-Bold", 9)
            pdf.setFillColor(colors.HexColor("#8D1A1A"))
            pdf.drawString(margin, y, "DRAFT ONLY — NOT A CERTIFICATION")
            pdf.setFillColor(colors.black)
            y -= 24
            pdf.setFont("Helvetica", 9)
        pdf.drawString(margin, y, line)
        y -= 13

    for title, key in (
        ("Declared evidence references (not independently verified)", "evidence_refs"),
        ("Declared checks / tests (not independently run)", "checks"),
        ("Open evidence gaps", "evidence_gaps"),
    ):
        y -= 8
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(margin, y, title)
        y -= 16
        pdf.setFont("Helvetica", 9)
        entries = report.get(key)
        entries = entries if isinstance(entries, list) and entries else ["None supplied; absence is not evidence of conformity."]
        for entry in entries[:25]:
            for line in textwrap.wrap(str(entry)[:500], width=106) or [""]:
                if y < 110:
                    pdf.showPage()
                    y = page_height - 60
                    pdf.setFont("Helvetica-Bold", 9)
                    pdf.setFillColor(colors.HexColor("#8D1A1A"))
                    pdf.drawString(margin, y, "DRAFT ONLY — NOT A CERTIFICATION")
                    pdf.setFillColor(colors.black)
                    y -= 24
                    pdf.setFont("Helvetica", 9)
                pdf.drawString(margin + 8, y, "• " + line)
                y -= 12

    if y < 115:
        pdf.showPage()
        y = page_height - 60
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(margin, y, "Verify this exact report")
    qr = QrCodeWidget(verification_url)
    bounds = qr.getBounds()
    qr_width = max(1.0, bounds[2] - bounds[0])
    qr_height = max(1.0, bounds[3] - bounds[1])
    qr_size = 72.0
    drawing = Drawing(qr_size, qr_size, transform=[qr_size / qr_width, 0, 0, qr_size / qr_height, 0, 0])
    drawing.add(qr)
    renderPDF.draw(drawing, pdf, margin, max(35, y - 82))
    pdf.setFont("Helvetica", 8)
    for idx, line in enumerate(textwrap.wrap(verification_url, width=85)[:3]):
        pdf.drawString(margin + 84, y - 15 - (idx * 12), line)
    pdf.setFillColor(colors.HexColor("#8D1A1A"))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(margin, 28, "NOT VALID AS CE / UL / ISO / RoHS / FCC CERTIFICATION")
    pdf.setFillColor(colors.black)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


__all__ = [
    "DRAFT_WARNING",
    "SUPPORTED_REPORT_KINDS",
    "build_compliance_readiness_pdf",
    "canonical_sha256",
]
