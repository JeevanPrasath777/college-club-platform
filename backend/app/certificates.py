import os
import uuid
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

CERT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", "certificates")


def generate_certificate_pdf(
    student_name: str,
    ra_number: str,
    event_title: str,
    club_name: str,
    verification_id: str,
    issued_at: datetime,
    event_start_at: datetime | None = None,
    participation_role: str = "Participant",
) -> str:
    os.makedirs(CERT_DIR, exist_ok=True)
    filename = f"{verification_id}.pdf"
    path = os.path.join(CERT_DIR, filename)
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    c.setStrokeColorRGB(0.05, 0.22, 0.45)
    c.setLineWidth(4)
    c.rect(0.5 * inch, 0.5 * inch, width - inch, height - inch)
    c.setFont("Times-Bold", 28)
    c.drawCentredString(width / 2, height - 1.6 * inch, "College Club Platform")
    c.setFont("Times-Italic", 16)
    c.drawCentredString(width / 2, height - 2.1 * inch, "Certificate of Participation")
    c.setFont("Times-Roman", 13)
    c.drawCentredString(width / 2, height - 3.0 * inch, "This is to certify that")
    c.setFont("Times-Bold", 20)
    c.drawCentredString(width / 2, height - 3.5 * inch, student_name)
    if ra_number:
        c.setFont("Times-Roman", 12)
        c.drawCentredString(width / 2, height - 3.9 * inch, f"RA Number: {ra_number}")
    c.setFont("Times-Roman", 13)
    c.drawCentredString(width / 2, height - 4.5 * inch, f"has participated as {participation_role} in")
    c.setFont("Times-Bold", 16)
    c.drawCentredString(width / 2, height - 5.0 * inch, event_title)
    c.setFont("Times-Roman", 12)
    c.drawCentredString(width / 2, height - 5.5 * inch, f"organized by {club_name}")
    if event_start_at:
        c.drawCentredString(width / 2, height - 5.9 * inch, f"Event date: {event_start_at.strftime('%d %B %Y')}")
    c.drawCentredString(width / 2, height - 6.3 * inch, f"Issued: {issued_at.strftime('%d %B %Y')}")
    c.setFont("Courier", 11)
    c.drawCentredString(width / 2, 1.2 * inch, f"Verification ID: {verification_id}")
    c.save()
    return path


def new_verification_id() -> str:
    return uuid.uuid4().hex.upper()
