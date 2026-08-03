"""Fill the Excel receipt template and render it to PDF via LibreOffice.

The template is a *design-heavy* workbook: a full-page background banner, the
"Lawrence Rentals" logo, and a "PAID" watermark are all embedded images. Saving
it through openpyxl mangles those images, so instead we edit only the target
cell values directly inside the .xlsx zip and copy every other part
(drawings, media, styles, sharedStrings) byte-for-byte. This keeps the receipt
looking exactly like the manual template.

Template cell map (sheet "Simple Receipt (light)"):
    C4   INVOICE #                 H4   DATE (serial)
    H7   BILL TO customer name     H8   BILL TO customer phone
    B13  line-1 description        H13  line-1 amount (rent)
    B14  line-2 description        H14  line-2 amount (parking)
    H28  TOTAL = SUM(H13:H27)  (formula, untouched)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date
from xml.sax.saxutils import escape

from app.pipeline.store import Tenant

SHEET_PATH = "xl/worksheets/sheet1.xml"
# Excel's day 0 is 1899-12-30 (accounting for the 1900 leap-year bug).
_EXCEL_EPOCH = date(1899, 12, 30)


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", text or "")


def receipt_basename(invoice_no: int, tenant: Tenant, period: str) -> str:
    period_slug = _safe(period.replace(" ", "-"))
    return f"Receipt_{invoice_no:03d}_{_safe(tenant.display_name)}_{period_slug}"


def _num_str(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _find_cell(xml: str, coord: str):
    """Return (match, style_index) for the <c r="COORD"...> element."""
    m = re.search(
        r'<c\b[^>]*\br="%s"[^>]*?(?:/>|>.*?</c>)' % re.escape(coord), xml, re.S
    )
    if not m:
        raise KeyError(f"cell {coord} not found in template")
    sm = re.search(r'\bs="(\d+)"', m.group(0))
    return m, (sm.group(1) if sm else None)


def _num_cell(coord: str, s, value) -> str:
    sattr = f' s="{s}"' if s else ""
    return f'<c r="{coord}"{sattr}><v>{_num_str(value)}</v></c>'


def _str_cell(coord: str, s, text: str) -> str:
    sattr = f' s="{s}"' if s else ""
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f'<c r="{coord}"{sattr} t="inlineStr"><is><t{space}>{escape(text)}</t></is></c>'


def _clear_cell(coord: str, s) -> str:
    sattr = f' s="{s}"' if s else ""
    return f'<c r="{coord}"{sattr}/>'


def fill_template(
    template_path: str,
    out_xlsx: str,
    tenant: Tenant,
    invoice_no: int,
    period: str,
    payment_date: date,
) -> str:
    """Write a filled .xlsx receipt, preserving the template's design. Returns out_xlsx."""
    zin = zipfile.ZipFile(template_path)
    try:
        xml = zin.read(SHEET_PATH).decode("utf-8")
        serial = (payment_date - _EXCEL_EPOCH).days

        # (coord, kind, value); kind: "n" number, "s" string, "clear" empty.
        edits = [
            ("C4", "n", invoice_no),
            ("H4", "n", serial),
            ("H7", "s", tenant.display_name),
            ("H8", "s", tenant.phone or ""),
            ("B13", "s", f"{period} Rental Charge"),
            ("H13", "n", tenant.monthly_rent),
        ]
        if tenant.parking_fee and tenant.parking_fee > 0:
            edits += [("B14", "s", "Parking Charge"), ("H14", "n", tenant.parking_fee)]
        else:
            edits += [("B14", "clear", None), ("H14", "clear", None)]

        # Resolve spans first, then splice back-to-front so offsets stay valid.
        replacements = []
        for coord, kind, value in edits:
            m, s = _find_cell(xml, coord)
            if kind == "n":
                new = _num_cell(coord, s, value)
            elif kind == "s":
                new = _str_cell(coord, s, value)
            else:
                new = _clear_cell(coord, s)
            replacements.append((m.start(), m.end(), new))
        for start, end, new in sorted(replacements, reverse=True):
            xml = xml[:start] + new + xml[end:]

        os.makedirs(os.path.dirname(out_xlsx), exist_ok=True)
        with zipfile.ZipFile(out_xlsx, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = xml.encode("utf-8") if item.filename == SHEET_PATH else zin.read(item.filename)
                zout.writestr(item, data)
    finally:
        zin.close()
    return out_xlsx


def xlsx_to_pdf(xlsx_path: str, out_dir: str, soffice_bin: str = "soffice") -> str:
    """Convert an .xlsx to PDF using headless LibreOffice. Returns the PDF path."""
    os.makedirs(out_dir, exist_ok=True)
    # Isolated profile dir so a running LibreOffice instance can't lock us out.
    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile:
        cmd = [
            soffice_bin,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to",
            "pdf",
            "--outdir",
            out_dir,
            xlsx_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    pdf_path = os.path.join(
        out_dir, os.path.splitext(os.path.basename(xlsx_path))[0] + ".pdf"
    )
    if result.returncode != 0 or not os.path.exists(pdf_path):
        raise RuntimeError(
            f"LibreOffice PDF conversion failed (code {result.returncode}): "
            f"{result.stderr or result.stdout}"
        )
    return pdf_path


def render_receipt(
    template_path: str,
    receipts_dir: str,
    tenant: Tenant,
    invoice_no: int,
    period: str,
    payment_date: date,
    soffice_bin: str = "soffice",
    make_pdf: bool = True,
) -> dict:
    """Produce the filled .xlsx and (optionally) a PDF. Returns their paths."""
    base = receipt_basename(invoice_no, tenant, period)
    xlsx_path = os.path.join(receipts_dir, base + ".xlsx")
    fill_template(template_path, xlsx_path, tenant, invoice_no, period, payment_date)

    out = {"xlsx": xlsx_path, "pdf": None}
    if make_pdf and shutil.which(soffice_bin):
        out["pdf"] = xlsx_to_pdf(xlsx_path, receipts_dir, soffice_bin)
    return out
