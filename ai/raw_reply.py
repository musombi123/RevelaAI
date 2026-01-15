from flask import send_file
from utils.document_export import create_docx, create_pdf
from io import BytesIO

export_type = request.args.get("export")  # docx | pdf

if export_type == "docx":
    file_bytes = create_docx(raw_reply)
    return send_file(
        BytesIO(file_bytes),
        as_attachment=True,
        download_name="revelaai_document.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

if export_type == "pdf":
    file_bytes = create_pdf(raw_reply)
    return send_file(
        BytesIO(file_bytes),
        as_attachment=True,
        download_name="revelaai_document.pdf",
        mimetype="application/pdf"
    )
