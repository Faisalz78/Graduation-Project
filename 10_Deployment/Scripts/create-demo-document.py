from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

root = Path(__file__).resolve().parents[2]
directory = root / ".local" / "samples"
directory.mkdir(parents=True, exist_ok=True)
writer = PdfWriter()
page = writer.add_blank_page(width=595, height=842)
font = DictionaryObject(
    {
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }
)
page[NameObject("/Resources")] = DictionaryObject(
    {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
)
stream = DecodedStreamObject()
stream.set_data(
    b"BT /F1 22 Tf 55 760 Td (DEMO INVOICE) Tj /F1 11 Tf 0 -35 Td (Synthetic document for local application testing.) Tj 0 -25 Td (Project: Headquarters development) Tj 0 -25 Td (Reference: DEMO-001) Tj 0 -25 Td (This is not a real invoice and is not payable.) Tj ET"
)
page[NameObject("/Contents")] = writer._add_object(stream)
writer.write(directory / "demo-invoice.pdf")
print("Synthetic sample created: .local/samples/demo-invoice.pdf")
