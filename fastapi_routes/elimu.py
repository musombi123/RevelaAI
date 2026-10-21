"""Authenticated Elimu learning, profile export, and signed certificate APIs."""
from __future__ import annotations

import hashlib
import io
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

import jwt
import qrcode
import requests
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Image as FlowImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.utils import ImageReader
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from revela_platform.auth.auth_gate import enforce_auth
from revela_platform.elimu_store import ElimuStoreUnavailable, collection, get_database, safe_document

router = APIRouter(tags=["Elimu Learning", "Account Profile", "Certificates"])
CERT_ISSUER = "RevelaCode"
CERT_AUDIENCE = "RevelaCode Certificate Verification"
PUBLIC_BASE_URL = "https://revelacode.co.ke"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat()
    return str(value)


def _store_call(fn):
    try:
        return fn()
    except ElimuStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": "elimu_store_unavailable", "message": "Learning data is temporarily unavailable."}) from exc


def _identifier(doc: dict[str, Any]) -> str:
    return str(doc.get("id") or doc.get("_id") or doc.get("hub_id") or doc.get("course_id") or doc.get("lesson_id") or doc.get("slug") or "")


def _id_query(value: str) -> dict[str, Any]:
    value = str(value or "").strip()
    if not value or len(value) > 160:
        raise HTTPException(status_code=422, detail="A valid resource ID is required.")
    clauses: list[dict[str, Any]] = [{"id": value}, {"slug": value}]
    try:
        clauses.append({"_id": ObjectId(value)})
    except (InvalidId, TypeError, ValueError):
        pass
    return {"$or": clauses}


def _hub_by_id(hub_id: str) -> dict[str, Any]:
    hub = _store_call(lambda: collection("elimu_hubs").find_one(_id_query(hub_id)))
    if not hub:
        raise HTTPException(status_code=404, detail={"code": "hub_not_found", "message": "Learning hub was not found."})
    if hub.get("is_published") is False or hub.get("published") is False or str(hub.get("status") or "").lower() in {"draft", "private", "archived"}:
        raise HTTPException(status_code=404, detail={"code": "hub_not_found", "message": "Learning hub was not found."})
    return hub


def _courses(hub: dict[str, Any]) -> list[dict[str, Any]]:
    raw = hub.get("courses")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _course(hub: dict[str, Any], course_id: str) -> dict[str, Any]:
    candidate = next((course for course in _courses(hub) if _identifier(course) == str(course_id)), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail={"code": "course_not_found", "message": "Course does not belong to this hub."})
    return candidate


def _lessons(course: dict[str, Any]) -> list[dict[str, Any]]:
    raw = course.get("lessons")
    if not isinstance(raw, list):
        return []
    result = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, str):
            # A string lesson is valid content; it receives a stable one-based
            # position ID so the UI can submit an identifier without guessing.
            result.append({"id": str(i + 1), "title": item})
    return result


def _lesson_id(lesson: dict[str, Any]) -> str:
    return str(lesson.get("id") or lesson.get("_id") or lesson.get("lesson_id") or "")


def _upstream_account_profile(claims: dict[str, Any]) -> dict[str, Any]:
    """Fetch non-secret profile metadata from the authoritative account API."""
    token = str(claims.get("_access_token") or "").strip()
    try:
        from fastapi_routes.auth import REVELACODE_BACKEND_URL, VERIFY_TIMEOUT_SECONDS
        base_url = str(REVELACODE_BACKEND_URL or "").strip().rstrip("/")
    except Exception:
        base_url = str(os.getenv("REVELACODE_BACKEND_URL", "")).strip().rstrip("/")
        try:
            timeout = max(1.0, min(15.0, float(os.getenv("REVELACODE_VERIFY_TIMEOUT_SECONDS", "4"))))
        except (TypeError, ValueError):
            timeout = 4.0
    else:
        timeout = VERIFY_TIMEOUT_SECONDS

    if not token or not base_url:
        return {}
    try:
        response = requests.get(
            f"{base_url}/api/user/me",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
        )
        if not response.ok:
            return {}
        payload = response.json()
    except (requests.RequestException, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    candidate = payload.get("data") or payload.get("user") or payload.get("profile") or payload
    return candidate if isinstance(candidate, dict) else {}


def _user_roles(claims: dict[str, Any]) -> list[str]:
    raw = claims.get("roles")
    roles = [str(role).strip() for role in raw if str(role).strip()] if isinstance(raw, list) else []
    role = str(claims.get("role") or "").strip()
    if role and role not in roles:
        roles.append(role)
    return list(dict.fromkeys(roles))


def _user_name(claims: dict[str, Any]) -> str:
    return str(claims.get("full_name") or claims.get("fullName") or claims.get("name") or claims.get("contact") or "RevelaCode Learner").strip()


def _progress_doc(user_id: str, hub_id: str) -> dict[str, Any] | None:
    return _store_call(lambda: collection("elimu_progress").find_one({"user_id": user_id, "hub_id": hub_id}))


def _progress_index(progress: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    entries = progress.get("courses", []) if isinstance(progress, dict) else []
    return {
        str(item.get("course_id")): item
        for item in entries
        if isinstance(item, dict) and item.get("course_id") is not None
    }


def _learning_totals(hub: dict[str, Any], progress: dict[str, Any] | None) -> dict[str, Any]:
    courses = _courses(hub)
    index = _progress_index(progress)
    total_lessons = 0
    completed_lessons = 0
    completed_courses = 0
    for course in courses:
        cid = _identifier(course)
        lesson_ids = {_lesson_id(lesson) for lesson in _lessons(course) if _lesson_id(lesson)}
        current = index.get(cid, {})
        completed = {str(item) for item in current.get("completed_lessons", [])}
        total_lessons += len(lesson_ids)
        completed_lessons += len(lesson_ids.intersection(completed))
        if lesson_ids and lesson_ids.issubset(completed):
            completed_courses += 1
    percent = int((completed_lessons * 100) / total_lessons) if total_lessons else 0
    complete = bool(courses) and total_lessons > 0 and completed_lessons == total_lessons
    return {
        "progress_percent": 100 if complete else percent,
        "completed_lessons": completed_lessons,
        "total_lessons": total_lessons,
        "completed_courses": completed_courses,
        "total_courses": len(courses),
        "hub_completed": complete,
    }


def _get_private_key() -> RSAPrivateKey:
    raw = os.getenv("REVELACODE_CERTIFICATE_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    path = os.getenv("REVELACODE_CERTIFICATE_PRIVATE_KEY_PATH", "").strip()
    if not raw and path:
        try:
            with open(path, "rb") as fh:
                key = serialization.load_pem_private_key(fh.read(), password=None)
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"code": "certificate_signing_not_configured", "message": "The certificate private key could not be loaded."}) from exc
    elif raw:
        try:
            key = serialization.load_pem_private_key(raw.encode("utf-8"), password=None)
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"code": "certificate_signing_not_configured", "message": "The certificate private key is not a valid PEM key."}) from exc
    else:
        raise HTTPException(status_code=503, detail={"code": "certificate_signing_not_configured", "message": "Set REVELACODE_CERTIFICATE_PRIVATE_KEY or REVELACODE_CERTIFICATE_PRIVATE_KEY_PATH before issuing certificates."})
    if not isinstance(key, RSAPrivateKey):
        raise HTTPException(status_code=503, detail={"code": "certificate_signing_key_type_invalid", "message": "Certificate signing requires an RSA private key."})
    return key


def _get_public_key() -> RSAPublicKey:
    raw = os.getenv("REVELACODE_CERTIFICATE_PUBLIC_KEY", "").replace("\\n", "\n").strip()
    if raw:
        try:
            key = serialization.load_pem_public_key(raw.encode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"code": "certificate_verification_not_configured", "message": "The certificate public key is not a valid PEM key."}) from exc
    else:
        key = _get_private_key().public_key()
    if not isinstance(key, RSAPublicKey):
        raise HTTPException(status_code=503, detail={"code": "certificate_public_key_type_invalid", "message": "Certificate verification requires an RSA public key."})
    return key


def _certificate_record(cert_id: str) -> dict[str, Any] | None:
    return _store_call(lambda: collection("revela_certificates").find_one({"certificate_id": str(cert_id)}))


def _validate_certificate(record: dict[str, Any]) -> dict[str, Any] | None:
    token = str(record.get("signed_token") or "")
    if not token:
        return None
    try:
        claims = jwt.decode(
            token,
            _get_public_key(),
            algorithms=["RS256"],
            issuer=CERT_ISSUER,
            audience=CERT_AUDIENCE,
            options={"require": ["iat", "iss", "aud", "cert_id", "sub", "hub_id"]},
        )
    except HTTPException:
        raise
    except jwt.InvalidTokenError:
        return None
    if (
        str(claims.get("cert_id")) != str(record.get("certificate_id"))
        or str(claims.get("sub")) != str(record.get("user_id"))
        or str(claims.get("hub_id")) != str(record.get("hub_id"))
    ):
        return None
    return claims


def _certificate_id() -> str:
    return "RC-EL-" + _now().strftime("%Y%m%d") + "-" + os.urandom(6).hex().upper()


def _certificate_pdf(record: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    pdf.setTitle("Highly Certified by RevelaCode - " + str(record.get("certificate_id", "")))
    pdf.setAuthor("RevelaCode Certification Authority")

    # Elegant double border and a low-contrast diagonal watermark.
    pdf.setFillColor(colors.HexColor("#F8FAFC"))
    pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    pdf.setStrokeColor(colors.HexColor("#0A74DA"))
    pdf.setLineWidth(2.2)
    pdf.rect(12 * mm, 12 * mm, page_width - 24 * mm, page_height - 24 * mm, fill=0, stroke=1)
    pdf.setStrokeColor(colors.HexColor("#D4AF37"))
    pdf.setLineWidth(0.8)
    pdf.rect(16 * mm, 16 * mm, page_width - 32 * mm, page_height - 32 * mm, fill=0, stroke=1)
    pdf.saveState()
    pdf.translate(page_width / 2, page_height / 2)
    pdf.rotate(28)
    pdf.setFillColor(colors.Color(0.04, 0.45, 0.85, alpha=0.055))
    pdf.setFont("Helvetica-Bold", 48)
    pdf.drawCentredString(0, 0, "REVELACODE VERIFIED")
    pdf.restoreState()

    # Compact vector mark/wordmark: does not depend on an arbitrary external logo URL.
    pdf.setFillColor(colors.HexColor("#0A74DA"))
    pdf.circle(35 * mm, page_height - 30 * mm, 8 * mm, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawCentredString(35 * mm, page_height - 34 * mm, "R")
    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("Helvetica-Bold", 19)
    pdf.drawString(48 * mm, page_height - 29 * mm, "RevelaCode")
    pdf.setFillColor(colors.HexColor("#2E8B57"))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(48 * mm, page_height - 35 * mm, "HIGHLY CERTIFIED LEARNING CREDENTIAL")

    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("Helvetica-Bold", 28)
    pdf.drawCentredString(page_width / 2, page_height - 52 * mm, "CERTIFICATE OF COMPLETION")
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(page_width / 2, page_height - 64 * mm, "This credential certifies that")
    pdf.setFillColor(colors.HexColor("#0A4F99"))
    pdf.setFont("Helvetica-Bold", 25)
    pdf.drawCentredString(page_width / 2, page_height - 77 * mm, str(record.get("user_name") or "RevelaCode Learner")[:100])
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(page_width / 2, page_height - 88 * mm, "has successfully completed the learning requirements for")
    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("Helvetica-Bold", 19)
    pdf.drawCentredString(page_width / 2, page_height - 100 * mm, str(record.get("hub_name") or "Elimu Hub")[:110])

    detail_y = page_height - 113 * mm
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#334155"))
    pdf.drawCentredString(page_width / 2, detail_y, f"Completion: 100%  |  Lessons: {record.get('completed_lessons', 0)}  |  Score: {record.get('score_label') or 'Not assessed'}")
    pdf.drawCentredString(page_width / 2, detail_y - 6 * mm, f"Issued: {str(record.get('issued_at', ''))[:10]}  |  Time spent: {record.get('time_spent_label') or 'Not recorded'}")

    roles = record.get("roles") if isinstance(record.get("roles"), list) else []
    roles_text = "  •  ".join(str(role) for role in roles[:6]) or "Elimu Learner"
    pdf.setFillColor(colors.HexColor("#166534"))
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawCentredString(page_width / 2, detail_y - 14 * mm, "CERTIFIED ROLES")
    pdf.setFillColor(colors.HexColor("#334155"))
    pdf.setFont("Helvetica", 8.5)
    pdf.drawCentredString(page_width / 2, detail_y - 20 * mm, roles_text[:180])

    skills = record.get("skills") if isinstance(record.get("skills"), list) else []
    skill_text = " • ".join(str(skill) for skill in skills[:8]) or "Learning outcomes recorded by the hub"
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(page_width / 2, detail_y - 27 * mm, ("Skills: " + skill_text)[:180])

    verify_url = str(record.get("verification_url") or f"{PUBLIC_BASE_URL}/verify/certificate/{quote(str(record.get('certificate_id', '')))}")
    qr_buffer = io.BytesIO()
    qrcode.make(verify_url).save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    pdf.drawImage(ImageReader(qr_buffer), page_width - 48 * mm, 22 * mm, width=26 * mm, height=26 * mm, preserveAspectRatio=True, mask="auto")
    pdf.setFont("Helvetica", 7)
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.drawCentredString(page_width - 35 * mm, 19 * mm, "SCAN TO VERIFY")

    pdf.setStrokeColor(colors.HexColor("#64748B"))
    pdf.line(23 * mm, 29 * mm, 78 * mm, 29 * mm)
    pdf.setFillColor(colors.HexColor("#0F172A"))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawCentredString(50.5 * mm, 24 * mm, str(record.get("signer_name") or "RevelaCode Certification Authority")[:55])
    pdf.setFont("Helvetica", 7)
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.drawCentredString(50.5 * mm, 19 * mm, "Digitally signed by certificate authority")

    fingerprint = hashlib.sha256(str(record.get("signed_token") or "").encode("utf-8")).hexdigest()
    pdf.setFont("Courier", 6.4)
    pdf.drawString(88 * mm, 20 * mm, "Certificate ID: " + str(record.get("certificate_id", "")))
    pdf.drawString(88 * mm, 16 * mm, "SHA-256 signature fingerprint: " + fingerprint[:36])
    pdf.setFont("Helvetica-Oblique", 6.5)
    pdf.drawString(88 * mm, 12.5 * mm, "Verify the digital signature and credential record before relying on this certificate.")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _profile_pdf(profile: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="RevelaCode Account Profile",
        author="RevelaCode",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="RCHeading", parent=styles["Heading1"], textColor=colors.HexColor("#0A4F99"), spaceAfter=7))
    styles.add(ParagraphStyle(name="RCHub", parent=styles["Heading2"], textColor=colors.HexColor("#166534"), spaceBefore=12, spaceAfter=4))
    styles.add(ParagraphStyle(name="RCSmall", parent=styles["BodyText"], fontSize=8.5, leading=11, textColor=colors.HexColor("#334155")))
    story = [
        Paragraph("RevelaCode", styles["Title"]),
        Paragraph("ACCOUNT PROFILE & LEARNING RECORD", styles["RCHeading"]),
        Paragraph("Generated from the authenticated account and recorded learning progress.", styles["RCSmall"]),
        Spacer(1, 8),
    ]
    user = profile.get("user", {})
    rows = [
        ["Name", str(user.get("name") or "Not provided")],
        ["Email / Contact", str(user.get("email") or "Not provided")],
        ["Roles", ", ".join(user.get("roles") or []) or "Not provided"],
        ["Joined", str(user.get("joined_at") or "Not provided by account token")],
        ["Hubs in use", str(len(profile.get("hubs") or []))],
        ["Certificates", str(len(profile.get("certificates") or []))],
    ]
    table = Table(rows, colWidths=[42 * mm, 130 * mm], repeatRows=0)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EFF6FF")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([table, Spacer(1, 12), Paragraph("Learning Hubs", styles["RCHeading"])])

    for hub in profile.get("hubs") or []:
        title = str(hub.get("name") or hub.get("hub_id") or "Learning hub")
        content = [
            Paragraph(title, styles["RCHub"]),
            Paragraph(str(hub.get("description") or "Description not present in source hub record."), styles["RCSmall"]),
        ]
        pairs = [
            ("Hub ID", hub.get("id") or hub.get("hub_id") or ""),
            ("Progress", f"{hub.get('progress_percent', 0)}%"),
            ("Lessons completed", f"{hub.get('completed_lessons', 0)} / {hub.get('total_lessons', 0)}"),
            ("Time spent", hub.get("time_spent_label") or "Not recorded"),
            ("Last accessed", hub.get("last_accessed") or "Not recorded"),
            ("Completion date", hub.get("completion_date") or "Not completed"),
            ("Certificate status", hub.get("certificate_status") or "Not issued"),
            ("Skills", ", ".join(hub.get("skills") or []) or "No skills list supplied"),
            ("Instructors", ", ".join(hub.get("instructors") or []) or "Not listed"),
        ]
        data = [[str(k), str(v or "Not provided")] for k, v in pairs]
        sub = Table(data, colWidths=[42 * mm, 130 * mm])
        sub.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#334155")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        content.append(sub)
        story.append(KeepTogether(content))

    certificates = profile.get("certificates") or []
    story.extend([Spacer(1, 10), Paragraph("Certificates", styles["RCHeading"])])
    if certificates:
        cert_rows = [["Certificate ID", "Hub", "Issued"]]
        cert_rows.extend([[str(c.get("certificate_id") or ""), str(c.get("hub_name") or ""), str(c.get("issued_at") or "")[:10]] for c in certificates])
        cert_table = Table(cert_rows, colWidths=[48 * mm, 86 * mm, 38 * mm], repeatRows=1)
        cert_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(cert_table)
    else:
        story.append(Paragraph("No issued certificates are recorded for this account.", styles["RCSmall"]))

    story.extend([Spacer(1, 14), Paragraph("Private account information. Share this export only with people you trust.", styles["RCSmall"])])
    doc.build(story)
    return buffer.getvalue()


def _profile_for(claims: dict[str, Any]) -> dict[str, Any]:
    user_id = str(claims.get("sub") or "")
    progress_docs = _store_call(lambda: list(collection("elimu_progress").find({"user_id": user_id})))
    certificates = _store_call(lambda: list(collection("revela_certificates").find({"user_id": user_id}).sort("issued_at", -1)))
    hubs_output: list[dict[str, Any]] = []
    for progress in progress_docs:
        try:
            hub = _hub_by_id(str(progress.get("hub_id") or ""))
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        totals = _learning_totals(hub, progress)
        cert = next((c for c in certificates if str(c.get("hub_id")) == str(progress.get("hub_id"))), None)
        raw_skills = hub.get("skills") if isinstance(hub.get("skills"), list) else []
        skills = [str(v.get("name") or v.get("title")) if isinstance(v, dict) else str(v) for v in raw_skills]
        for course in _courses(hub):
            extra = course.get("skills") if isinstance(course.get("skills"), list) else []
            skills.extend(str(v.get("name") or v.get("title")) if isinstance(v, dict) else str(v) for v in extra)
        skills = list(dict.fromkeys(v for v in skills if v and v != "None"))
        instructors_raw = hub.get("instructors") if isinstance(hub.get("instructors"), list) else []
        instructors = [str(v.get("name") or v.get("full_name")) if isinstance(v, dict) else str(v) for v in instructors_raw]
        hubs_output.append({
            "id": _identifier(hub),
            "hub_id": str(progress.get("hub_id")),
            "name": str(hub.get("name") or hub.get("title") or hub.get("hub_name") or "Learning hub"),
            "description": str(hub.get("description") or ""),
            "skills": skills,
            "instructors": instructors,
            **totals,
            "time_spent_seconds": int(progress.get("time_spent_seconds") or 0),
            "time_spent_label": _duration_label(progress.get("time_spent_seconds")),
            "last_accessed": _iso(progress.get("last_accessed")),
            "completion_date": _iso(progress.get("completed_at")),
            "certificate_status": "Issued" if cert else ("Eligible" if totals["hub_completed"] else "Not earned"),
            "certificate_id": cert.get("certificate_id") if cert else None,
            "courses": safe_document(_courses(hub)),
        })
    certs_out = [
        {
            "certificate_id": c.get("certificate_id"),
            "hub_id": c.get("hub_id"),
            "hub_name": c.get("hub_name"),
            "issued_at": _iso(c.get("issued_at")),
            "verification_url": c.get("verification_url"),
        }
        for c in certificates
    ]
    account = _upstream_account_profile(claims)
    return {
        "user": {
            "id": str(account.get("id") or account.get("_id") or user_id),
            "name": str(account.get("full_name") or account.get("fullName") or account.get("name") or _user_name(claims)),
            "email": str(account.get("email") or account.get("contact") or claims.get("contact") or claims.get("email") or ""),
            "contact": str(account.get("contact") or claims.get("contact") or ""),
            "roles": _user_roles(claims),
            "avatar": account.get("avatar") or account.get("avatar_url") or claims.get("avatar") or claims.get("avatar_url"),
            "joined_at": _iso(account.get("created_at") or account.get("createdAt") or claims.get("created_at") or claims.get("joined_at") or claims.get("createdAt")),
        },
        "hubs": hubs_output,
        "certificates": certs_out,
        "certificates_count": len(certs_out),
        "generated_at": _now().isoformat(),
    }


def _duration_label(value: Any) -> str:
    seconds = max(0, int(value or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s" if seconds else "Not recorded"


class ProgressUpdate(BaseModel):
    hub_id: str = Field(min_length=1, max_length=160)
    course_id: str = Field(min_length=1, max_length=160)
    action: Literal["start", "complete_lesson", "complete_course"]
    lesson_id: str | None = Field(default=None, max_length=160)
    time_spent_seconds: int = Field(default=0, ge=0, le=86400)


@router.get("/api/auth/me")
async def auth_me(claims: dict[str, Any] = Depends(enforce_auth)) -> dict[str, Any]:
    """Return the signed-in user's JWT identity after live upstream account verification."""
    return {
        "success": True,
        "user": {
            "id": str(claims.get("sub")),
            "full_name": _user_name(claims),
            "contact": str(claims.get("contact") or claims.get("email") or ""),
            "role": str(claims.get("role") or "user"),
            "roles": _user_roles(claims),
            "verified": bool(claims.get("verified", False)),
            "joined_at": _iso(claims.get("created_at") or claims.get("joined_at")),
        },
    }


@router.get("/api/elimu/hubs")
async def list_elimu_hubs(claims: dict[str, Any] = Depends(enforce_auth)) -> dict[str, Any]:
    def load():
        docs = list(collection("elimu_hubs").find({}).sort("name", 1))
        visible = [
            doc for doc in docs
            if doc.get("is_published") is not False
            and doc.get("published") is not False
            and str(doc.get("status") or "").lower() not in {"draft", "private", "archived"}
        ]
        return [safe_document({
            "id": _identifier(doc),
            "name": doc.get("name") or doc.get("title") or doc.get("hub_name") or "",
            "description": doc.get("description") or "",
            "skills": doc.get("skills") or [],
            "instructors": doc.get("instructors") or [],
            "courses_count": len(_courses(doc)),
        }) for doc in visible]
    hubs = _store_call(load)
    return {"success": True, "hubs": hubs, "count": len(hubs)}


@router.get("/api/elimu/hubs/{hub_id}")
async def get_elimu_hub(hub_id: str, claims: dict[str, Any] = Depends(enforce_auth)) -> dict[str, Any]:
    hub = _hub_by_id(hub_id)
    progress = _progress_doc(str(claims["sub"]), str(_identifier(hub)))
    totals = _learning_totals(hub, progress)
    progress_index = _progress_index(progress)
    courses_out = []
    for course in _courses(hub):
        cid = _identifier(course)
        current = progress_index.get(cid, {})
        lessons_out = []
        completed = {str(item) for item in current.get("completed_lessons", [])}
        for lesson in _lessons(course):
            lid = _lesson_id(lesson)
            lessons_out.append({
                **safe_document(lesson),
                "id": lid,
                "completed": lid in completed,
            })
        courses_out.append({
            **safe_document(course),
            "id": cid,
            "lessons": lessons_out,
            "status": current.get("status", "not_started"),
            "completed_lessons": len(completed),
        })
    return {
        "success": True,
        "hub": {
            **safe_document(hub),
            "id": _identifier(hub),
            "name": hub.get("name") or hub.get("title") or hub.get("hub_name") or "",
            "courses": courses_out,
            "progress": totals,
        },
    }


@router.get("/api/elimu/progress")
async def get_elimu_progress(
    hub_id: str | None = Query(default=None, max_length=160),
    claims: dict[str, Any] = Depends(enforce_auth),
) -> dict[str, Any]:
    user_id = str(claims["sub"])
    query: dict[str, Any] = {"user_id": user_id}
    if hub_id:
        query["hub_id"] = hub_id
    docs = _store_call(lambda: list(collection("elimu_progress").find(query).sort("last_accessed", -1)))
    items = []
    for progress in docs:
        try:
            hub = _hub_by_id(str(progress.get("hub_id") or ""))
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        items.append({
            "hub_id": str(progress.get("hub_id")),
            "hub_name": str(hub.get("name") or hub.get("title") or ""),
            **_learning_totals(hub, progress),
            "time_spent_seconds": int(progress.get("time_spent_seconds") or 0),
            "last_accessed": _iso(progress.get("last_accessed")),
            "completed_at": _iso(progress.get("completed_at")),
            "courses": safe_document(progress.get("courses") or []),
        })
    return {"success": True, "progress": items}


@router.post("/api/elimu/progress")
async def update_elimu_progress(
    payload: ProgressUpdate,
    claims: dict[str, Any] = Depends(enforce_auth),
) -> dict[str, Any]:
    user_id = str(claims["sub"])
    hub = _hub_by_id(payload.hub_id)
    hub_id = _identifier(hub)
    if not hub_id:
        raise HTTPException(status_code=500, detail="The stored learning hub has no stable identifier.")
    course = _course(hub, payload.course_id)
    course_id = _identifier(course)
    lessons = _lessons(course)
    lesson_ids = {_lesson_id(lesson) for lesson in lessons if _lesson_id(lesson)}
    if payload.action != "start" and not lesson_ids:
        raise HTTPException(status_code=409, detail={"code": "course_has_no_lessons", "message": "This course has no recorded lessons to complete."})

    now = _now()
    progress = _store_call(lambda: collection("elimu_progress").find_one({"user_id": user_id, "hub_id": hub_id}))
    if not progress:
        progress = {
            "user_id": user_id,
            "hub_id": hub_id,
            "courses": [],
            "time_spent_seconds": 0,
            "created_at": now,
        }
    course_entries = progress.get("courses") if isinstance(progress.get("courses"), list) else []
    current = next((entry for entry in course_entries if isinstance(entry, dict) and str(entry.get("course_id")) == course_id), None)
    if current is None:
        current = {"course_id": course_id, "completed_lessons": [], "status": "not_started"}
        course_entries.append(current)

    current["started_at"] = current.get("started_at") or now
    current["last_accessed"] = now
    if payload.action == "start":
        current["status"] = "in_progress"
    elif payload.action == "complete_lesson":
        if not payload.lesson_id or payload.lesson_id not in lesson_ids:
            raise HTTPException(status_code=422, detail={"code": "invalid_lesson", "message": "lesson_id must identify a lesson inside the selected course."})
        completed = {str(item) for item in current.get("completed_lessons", [])}
        completed.add(payload.lesson_id)
        current["completed_lessons"] = sorted(completed)
        current["status"] = "completed" if lesson_ids.issubset(completed) else "in_progress"
        if current["status"] == "completed":
            current["completed_at"] = now
    elif payload.action == "complete_course":
        completed = {str(item) for item in current.get("completed_lessons", [])}
        if not lesson_ids.issubset(completed):
            raise HTTPException(status_code=409, detail={"code": "lessons_incomplete", "message": "Complete every recorded lesson before completing this course."})
        current["status"] = "completed"
        current["completed_at"] = current.get("completed_at") or now

    progress["courses"] = course_entries
    progress["time_spent_seconds"] = max(0, int(progress.get("time_spent_seconds") or 0)) + payload.time_spent_seconds
    progress["last_accessed"] = now
    totals = _learning_totals(hub, progress)
    if totals["hub_completed"]:
        progress["completed_at"] = progress.get("completed_at") or now
    progress["progress_percent"] = totals["progress_percent"]
    _store_call(lambda: collection("elimu_progress").replace_one({"user_id": user_id, "hub_id": hub_id}, progress, upsert=True))
    return {
        "success": True,
        "message": "Learning progress saved.",
        "hub_id": hub_id,
        "course_id": course_id,
        **totals,
        "time_spent_seconds": progress["time_spent_seconds"],
        "last_accessed": now.isoformat(),
        "completed_at": _iso(progress.get("completed_at")),
        "certificate_eligible": totals["hub_completed"],
    }


@router.get("/api/accounts/profile/download")
async def download_profile(
    format: Literal["pdf", "json"] = Query(default="pdf"),
    claims: dict[str, Any] = Depends(enforce_auth),
):
    profile = _profile_for(claims)
    if format == "json":
        return JSONResponse(
            content=safe_document(profile),
            headers={"Content-Disposition": 'attachment; filename="revelacode-profile.json"'},
        )
    pdf_bytes = _profile_pdf(profile)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", profile["user"]["name"]).strip("-")[:64] or "user"
    filename = f"revelacode-profile-{safe_name}-{_now().strftime('%Y-%m-%d')}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/certificates/generate")
async def generate_certificate(
    payload: dict[str, Any],
    claims: dict[str, Any] = Depends(enforce_auth),
) -> dict[str, Any]:
    hub_id = str(payload.get("hub_id") or payload.get("hubId") or "").strip()
    if not hub_id:
        raise HTTPException(status_code=422, detail="hub_id is required.")
    hub = _hub_by_id(hub_id)
    stable_hub_id = _identifier(hub)
    progress = _progress_doc(str(claims["sub"]), stable_hub_id)
    totals = _learning_totals(hub, progress)
    if not totals["hub_completed"] or totals["progress_percent"] != 100:
        raise HTTPException(status_code=409, detail={"code": "hub_not_complete", "message": "Complete all recorded lessons in this hub before requesting its certificate."})

    existing = _store_call(lambda: collection("revela_certificates").find_one({"user_id": str(claims["sub"]), "hub_id": stable_hub_id}))
    if existing and _validate_certificate(existing):
        return {
            "success": True,
            "certificate_id": existing["certificate_id"],
            "cert_id": existing["certificate_id"],
            "verification_url": existing["verification_url"],
            "already_issued": True,
        }

    key = _get_private_key()
    cert_id = _certificate_id()
    roles = _user_roles(claims)
    hub_roles = ["Elimu Learner", "Hub Completion Verified"]
    certificate_roles = list(dict.fromkeys(roles + hub_roles + ["RevelaCode Certification Authority"]))
    skills: list[str] = []
    for skill in hub.get("skills", []) if isinstance(hub.get("skills"), list) else []:
        value = str(skill.get("name") or skill.get("title") or "") if isinstance(skill, dict) else str(skill)
        if value and value not in skills:
            skills.append(value)
    for course in _courses(hub):
        for skill in course.get("skills", []) if isinstance(course.get("skills"), list) else []:
            value = str(skill.get("name") or skill.get("title") or "") if isinstance(skill, dict) else str(skill)
            if value and value not in skills:
                skills.append(value)

    verify_url = f"{PUBLIC_BASE_URL}/verify/certificate/{quote(cert_id)}"
    issued = _now()
    progress_seconds = int((progress or {}).get("time_spent_seconds") or 0)
    score = (progress or {}).get("score")
    record = {
        "certificate_id": cert_id,
        "user_id": str(claims["sub"]),
        "user_name": _user_name(claims),
        "user_roles": _user_roles(claims),
        "hub_id": stable_hub_id,
        "hub_name": str(hub.get("name") or hub.get("title") or hub.get("hub_name") or "Elimu Hub"),
        "hub_roles": hub_roles,
        "roles": certificate_roles,
        "issuer": CERT_ISSUER,
        "issuer_role": "RevelaCode Certification Authority",
        "skills": skills,
        "completed_lessons": totals["completed_lessons"],
        "total_lessons": totals["total_lessons"],
        "progress_percent": 100,
        "score": score,
        "score_label": f"{score}%" if isinstance(score, (int, float)) else "Not assessed",
        "time_spent_seconds": progress_seconds,
        "time_spent_label": _duration_label(progress_seconds),
        "issued_at": issued,
        "verification_url": verify_url,
        "signer_name": os.getenv("REVELACODE_CERTIFICATE_SIGNER_NAME", "RevelaCode Certification Authority").strip() or "RevelaCode Certification Authority",
    }
    signed_claims = {
        "iss": CERT_ISSUER,
        "aud": CERT_AUDIENCE,
        "iat": int(issued.timestamp()),
        "cert_id": cert_id,
        "sub": str(claims["sub"]),
        "user_name": record["user_name"],
        "hub_id": stable_hub_id,
        "hub_name": record["hub_name"],
        "roles": certificate_roles,
        "skills": skills,
        "progress_percent": 100,
        "issued_at": issued.isoformat(),
    }
    try:
        token = jwt.encode(signed_claims, key, algorithm="RS256")
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "certificate_signing_failed", "message": "The certificate could not be digitally signed."}) from exc
    record["signed_token"] = token
    _store_call(lambda: collection("revela_certificates").insert_one(record))
    return {
        "success": True,
        "certificate_id": cert_id,
        "cert_id": cert_id,
        "verification_url": verify_url,
        "issued_at": issued.isoformat(),
        "roles": certificate_roles,
        "skills": skills,
        "download_url": f"/api/certificates/{quote(cert_id)}",
    }


@router.get("/api/certificates/{cert_id}")
async def download_certificate(
    cert_id: str,
    claims: dict[str, Any] = Depends(enforce_auth),
):
    record = _certificate_record(cert_id)
    if not record:
        raise HTTPException(status_code=404, detail={"code": "certificate_not_found", "message": "Certificate was not found."})
    if str(record.get("user_id")) != str(claims.get("sub")):
        raise HTTPException(status_code=403, detail={"code": "certificate_owner_mismatch", "message": "This certificate belongs to a different account."})
    signed = _validate_certificate(record)
    if not signed:
        raise HTTPException(status_code=409, detail={"code": "certificate_signature_invalid", "message": "The stored certificate signature is invalid."})
    raw = _certificate_pdf(record)
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{record["certificate_id"]}.pdf"'},
    )



@router.get("/api/verify/certificate/public-key")
async def certificate_public_key() -> dict[str, Any]:
    """Expose only the public key used to validate signed certificate JWTs."""
    key = _get_public_key()
    pem = key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return {
        "algorithm": "RS256",
        "issuer": CERT_ISSUER,
        "public_key_pem": pem,
        "fingerprint_sha256": hashlib.sha256(pem.encode("ascii")).hexdigest(),
    }


@router.get("/api/verify/certificate/{cert_id}")
async def verify_certificate(cert_id: str) -> dict[str, Any]:
    """Public QR target; exposes only the certificate's signed public metadata."""
    record = _certificate_record(cert_id)
    if not record:
        return JSONResponse(status_code=404, content={"valid": False, "certificate_id": cert_id, "reason": "certificate_not_found"})
    signed = _validate_certificate(record)
    if not signed:
        return JSONResponse(status_code=200, content={"valid": False, "certificate_id": cert_id, "reason": "signature_invalid"})
    fingerprint = hashlib.sha256(str(record.get("signed_token") or "").encode("utf-8")).hexdigest()
    return {
        "valid": True,
        "certified_by": CERT_ISSUER,
        "certificate_id": record["certificate_id"],
        "user": {
            "id": record.get("user_id"),
            "name": record.get("user_name"),
            "roles": record.get("user_roles") or [],
        },
        "hub": {
            "id": record.get("hub_id"),
            "name": record.get("hub_name"),
            "progress_percent": 100,
            "completed_lessons": record.get("completed_lessons", 0),
            "total_lessons": record.get("total_lessons", 0),
        },
        "roles": record.get("roles") or [],
        "skills": record.get("skills") or [],
        "issued_at": _iso(record.get("issued_at")),
        "verification_url": record.get("verification_url"),
        "signature_fingerprint_sha256": fingerprint,
        "signature_algorithm": "RS256",
        "issuer_role": record.get("issuer_role"),
    }
