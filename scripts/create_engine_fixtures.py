"""Generate synthetic PDF/DOCX samples for integration tests; no real PII."""
from pathlib import Path

from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def main():
    target = Path(__file__).resolve().parents[1] / ".run" / "fixtures"
    target.mkdir(exist_ok=True)
    doc = Document()
    for line in ["Resume: Fictional Engineer", "Skills: Python, SQL, FastAPI, Git",
                 "Experience: Software Engineer at Example Company, 2022-2025.",
                 "Built APIs with Python and PostgreSQL.", "Education: Bachelor in Computer Science, 2021."]:
        doc.add_paragraph(line)
    doc.save(target / "fictional-resume.docx")
    writer = PdfWriter()
    page = writer.add_blank_page(width=595,height=842)
    font = DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),
                             NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 780 Td (Fictional coffee company marketing brief.) Tj 0 -20 Td (Audience: office workers. Goal: draft a weekly content plan.) Tj ET")
    page[NameObject("/Contents")] = stream
    writer.write(target / "fictional-brief.pdf")
    print("Synthetic PDF and DOCX fixtures ready.")


if __name__ == "__main__":
    main()
