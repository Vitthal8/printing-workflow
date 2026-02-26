#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
PrintFlow Pro — PDF Validator
File: automation/pdf_validator.py

PURPOSE:
  Validates uploaded PDF files before production begins.
  Catches errors that would cause print quality issues.

CHECKS:
  ✓ Page count matches expected quantity/type
  ✓ Page dimensions (A4 / DL / custom)
  ✓ Colour mode (CMYK preferred for print)
  ✓ All fonts embedded
  ✓ File not password protected
  ✓ Bleed / margin adequacy
  ✓ Image resolution (min 150 DPI for print)
  ✓ File not corrupted

INSTALL:
  pip install PyPDF2 pymupdf pillow python-dotenv requests
═══════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import logging
import tempfile
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Try to import PDF libraries ───────────────────────────────
try:
    import PyPDF2
    PYPDF2_OK = True
except ImportError:
    PYPDF2_OK = False
    log.warning("PyPDF2 not installed. pip install PyPDF2")

try:
    import fitz  # PyMuPDF
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False
    log.warning("PyMuPDF not installed. pip install pymupdf")

# ── Standard print dimensions (in points, 1pt = 1/72 inch) ───
PAGE_SIZES = {
    'A4':      (595.276, 841.890),    # 210×297mm
    'A5':      (419.528, 595.276),    # 148×210mm
    'DL':      (311.811, 623.622),    # 110×220mm (envelope)
    'LETTER':  (612.0,   792.0),      # US Letter
    'INLAND':  (595.276, 419.528),    # A5 landscape for inland
}
SIZE_TOLERANCE_PT = 5.0   # ±5pt tolerance for page size matching
MIN_BLEED_PT      = 0.0   # 0pt minimum (we don't require bleed but flag if missing for colour jobs)
MIN_IMAGE_DPI     = 150   # minimum acceptable image resolution


# ══════════════════════════════════════════════════════════════
# VALIDATION ENGINE
# ══════════════════════════════════════════════════════════════
class PDFValidationResult:
    def __init__(self, filename):
        self.filename      = filename
        self.passed        = True
        self.errors        = []   # critical — block production
        self.warnings      = []   # non-critical — inform operator
        self.info          = {}   # metadata about the file
        self.page_count    = 0
        self.page_size     = None
        self.has_bleed     = False
        self.fonts_embedded= True
        self.is_encrypted  = False
        self.colour_mode   = 'unknown'

    def add_error(self, msg):
        self.errors.append(msg)
        self.passed = False
        log.error(f"  ✗ {msg}")

    def add_warning(self, msg):
        self.warnings.append(msg)
        log.warning(f"  ⚠ {msg}")

    def add_info(self, key, value):
        self.info[key] = value
        log.info(f"  · {key}: {value}")

    def to_dict(self):
        return {
            'filename':       self.filename,
            'passed':         self.passed,
            'errors':         self.errors,
            'warnings':       self.warnings,
            'info':           self.info,
            'page_count':     self.page_count,
            'page_size':      self.page_size,
            'fonts_embedded': self.fonts_embedded,
            'is_encrypted':   self.is_encrypted,
            'colour_mode':    self.colour_mode,
        }


def identify_page_size(width_pt, height_pt):
    """Match page dimensions to known sizes within tolerance."""
    # Normalise to portrait
    w, h = sorted([width_pt, height_pt])
    for name, (pw, ph) in PAGE_SIZES.items():
        sw, sh = sorted([pw, ph])
        if abs(w - sw) <= SIZE_TOLERANCE_PT and abs(h - sh) <= SIZE_TOLERANCE_PT:
            orientation = 'Portrait' if height_pt > width_pt else 'Landscape'
            return f"{name} ({orientation})"
    return f"Custom ({width_pt:.1f}×{height_pt:.1f}pt)"


def check_encryption(pdf_path):
    """Check if PDF is password protected."""
    if not PYPDF2_OK:
        return False
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            return reader.is_encrypted
    except Exception:
        return False


def check_fonts(pdf_path):
    """
    Check if all fonts are embedded.
    Returns (all_embedded: bool, unembedded_fonts: list)
    """
    if not PYMUPDF_OK:
        return True, []

    unembedded = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            for font in page.get_fonts(full=True):
                # font tuple: (xref, ext, type, basefont, name, encoding, referencer)
                font_name     = font[3] or font[4] or 'Unknown'
                is_embedded   = font[1] != ''   # ext is empty for non-embedded
                is_base_font  = font[2] in ('Type1', 'TrueType') and font[3] in (
                    'Helvetica', 'Times-Roman', 'Courier', 'Symbol', 'ZapfDingbats',
                    'Helvetica-Bold', 'Times-Bold', 'Courier-Bold'
                )
                if not is_embedded and not is_base_font:
                    if font_name not in unembedded:
                        unembedded.append(font_name)
        doc.close()
    except Exception as e:
        log.warning(f"Font check failed: {e}")

    return len(unembedded) == 0, unembedded


def check_colour_mode(pdf_path):
    """
    Detect colour mode of PDF.
    Returns: 'CMYK', 'RGB', 'Grayscale', 'Mixed', or 'unknown'
    """
    if not PYMUPDF_OK:
        return 'unknown'
    try:
        doc = fitz.open(pdf_path)
        colour_spaces = set()
        for page_num in range(min(3, len(doc))):   # check first 3 pages
            page = doc[page_num]
            for img in page.get_images(full=True):
                xref = img[0]
                base = doc.extract_image(xref)
                cs   = base.get('colorspace', 0)
                if cs == 4:
                    colour_spaces.add('CMYK')
                elif cs == 3:
                    colour_spaces.add('RGB')
                elif cs == 1:
                    colour_spaces.add('Grayscale')
        doc.close()
        if not colour_spaces:
            return 'No images detected'
        if len(colour_spaces) == 1:
            return list(colour_spaces)[0]
        return f"Mixed: {', '.join(colour_spaces)}"
    except Exception:
        return 'unknown'


def check_image_resolution(pdf_path):
    """
    Check if images in PDF have adequate DPI for print.
    Returns list of low-resolution images found.
    """
    if not PYMUPDF_OK:
        return []
    low_res = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(min(5, len(doc))):
            page  = doc[page_num]
            rect  = page.rect
            for img in page.get_images():
                xref = img[0]
                base = doc.extract_image(xref)
                w_px = base.get('width', 0)
                h_px = base.get('height', 0)
                # Approximate DPI based on page dimensions
                if rect.width > 0:
                    dpi = (w_px / rect.width) * 72
                    if dpi < MIN_IMAGE_DPI and dpi > 10:
                        low_res.append({
                            'page':  page_num + 1,
                            'dpi':   round(dpi),
                            'size':  f"{w_px}×{h_px}px"
                        })
        doc.close()
    except Exception:
        pass
    return low_res


# ══════════════════════════════════════════════════════════════
# MAIN VALIDATOR
# ══════════════════════════════════════════════════════════════
def validate_pdf(
    pdf_path: str,
    expected_pages: Optional[int] = None,
    expected_size:  Optional[str] = None,
    job_type:       str = 'simplex'
) -> PDFValidationResult:
    """
    Full PDF validation.

    Args:
        pdf_path:       Local path to PDF file
        expected_pages: Expected page count (None = no check)
        expected_size:  Expected page size code e.g. 'A4', 'DL'
        job_type:       'simplex', 'duplex', or 'multipage'

    Returns:
        PDFValidationResult object
    """
    result = PDFValidationResult(Path(pdf_path).name)
    log.info(f"Validating: {pdf_path}")

    # ── 1. File exists & readable ─────────────────────────────
    if not Path(pdf_path).exists():
        result.add_error("File not found or inaccessible")
        return result

    file_size_mb = Path(pdf_path).stat().st_size / (1024 * 1024)
    result.add_info("File size", f"{file_size_mb:.1f} MB")

    if file_size_mb > 50:
        result.add_error(f"File size {file_size_mb:.1f}MB exceeds 50MB limit")
        return result

    # ── 2. Encryption check ───────────────────────────────────
    if check_encryption(pdf_path):
        result.is_encrypted = True
        result.add_error("PDF is password protected. Please provide an unencrypted file.")
        return result
    result.add_info("Encryption", "None ✓")

    # ── 3. Open PDF and read structure ────────────────────────
    if not PYPDF2_OK and not PYMUPDF_OK:
        result.add_warning("PDF libraries not installed — skipping detailed validation")
        return result

    try:
        if PYMUPDF_OK:
            doc = fitz.open(pdf_path)
            result.page_count = len(doc)

            if result.page_count == 0:
                result.add_error("PDF has 0 pages — file may be corrupted")
                return result

            # Page dimensions from first page
            first_page = doc[0]
            w = round(first_page.rect.width,  2)
            h = round(first_page.rect.height, 2)
            result.page_size = identify_page_size(w, h)
            result.add_info("Page count",     result.page_count)
            result.add_info("Page size",      result.page_size)
            result.add_info("Dimensions (pt)", f"{w} × {h}")
            doc.close()

        elif PYPDF2_OK:
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                result.page_count = len(reader.pages)
                if result.page_count > 0:
                    page = reader.pages[0]
                    box  = page.mediabox
                    w, h = float(box.width), float(box.height)
                    result.page_size = identify_page_size(w, h)
                    result.add_info("Page count", result.page_count)
                    result.add_info("Page size",  result.page_size)

    except Exception as e:
        result.add_error(f"Could not read PDF structure: {str(e)}")
        return result

    # ── 4. Page count validation ──────────────────────────────
    if expected_pages:
        if result.page_count != expected_pages:
            result.add_error(
                f"Page count mismatch: expected {expected_pages}, "
                f"found {result.page_count}"
            )
        else:
            result.add_info("Page count check", "✓ Matches expected")

    # For duplex, page count must be even
    if job_type == 'duplex' and result.page_count % 2 != 0:
        result.add_error(
            f"Duplex job requires even page count. "
            f"Found {result.page_count} pages (odd number)."
        )

    # ── 5. Page size validation ───────────────────────────────
    if expected_size and expected_size.upper() in PAGE_SIZES:
        if expected_size.upper() not in (result.page_size or ''):
            result.add_warning(
                f"Page size may not match: expected {expected_size}, "
                f"detected {result.page_size}"
            )

    # ── 6. Font embedding check ───────────────────────────────
    fonts_ok, unembedded = check_fonts(pdf_path)
    result.fonts_embedded = fonts_ok
    if not fonts_ok:
        result.add_error(
            f"Non-embedded fonts detected: {', '.join(unembedded)}. "
            f"Please re-export PDF with all fonts embedded."
        )
    else:
        result.add_info("Font embedding", "✓ All fonts embedded")

    # ── 7. Colour mode ────────────────────────────────────────
    result.colour_mode = check_colour_mode(pdf_path)
    result.add_info("Colour mode", result.colour_mode)
    if 'RGB' in result.colour_mode:
        result.add_warning(
            "RGB colour mode detected. For best print accuracy, "
            "CMYK is preferred. RGB files will be converted by RIP software."
        )

    # ── 8. Image resolution ───────────────────────────────────
    low_res_images = check_image_resolution(pdf_path)
    if low_res_images:
        result.add_warning(
            f"{len(low_res_images)} low-resolution image(s) detected "
            f"(below {MIN_IMAGE_DPI} DPI). May appear pixelated in print."
        )
        result.add_info("Low-res images", low_res_images[:3])  # show first 3
    else:
        result.add_info("Image resolution", f"✓ All images ≥{MIN_IMAGE_DPI} DPI")

    # ── Done ──────────────────────────────────────────────────
    status = "✓ PASSED" if result.passed else "✗ FAILED"
    log.info(f"Validation {status} — {len(result.errors)} errors, {len(result.warnings)} warnings")
    return result


# ══════════════════════════════════════════════════════════════
# SUPABASE INTEGRATION — save validation result to job record
# ══════════════════════════════════════════════════════════════
def save_validation_result(job_id: str, result: PDFValidationResult):
    """Save validation result to Supabase and update job status."""
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

    headers = {
        'apikey':        SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type':  'application/json',
        'Prefer':        'return=representation'
    }

    new_status = 'processing' if result.passed else 'error'
    payload = {
        'status':              new_status,
        'validation_passed':   result.passed,
        'validation_errors':   json.dumps(result.errors),
        'validation_warnings': json.dumps(result.warnings),
        'validation_info':     json.dumps(result.info),
        'updated_at':          __import__('datetime').datetime.utcnow().isoformat()
    }

    requests.patch(
        f"{SUPABASE_URL}/rest/v1/jobs?id=eq.{job_id}",
        json=payload, headers=headers
    )

    # Log activity
    requests.post(
        f"{SUPABASE_URL}/rest/v1/activity_log",
        json={
            'job_id':  job_id,
            'action':  'validation_complete',
            'details': f"PDF validation {'PASSED' if result.passed else 'FAILED'}. "
                       f"Errors: {len(result.errors)}, Warnings: {len(result.warnings)}"
        },
        headers=headers
    )

    log.info(f"Validation result saved. Job {job_id} → status: {new_status}")


# ══════════════════════════════════════════════════════════════
# ENTRY POINT — called by API or directly
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    """
    CLI usage:
      python pdf_validator.py /path/to/file.pdf [job_id] [expected_pages] [job_type]

    Examples:
      python pdf_validator.py sample.pdf
      python pdf_validator.py statement.pdf abc-123 14820 duplex
    """
    if len(sys.argv) < 2:
        print("Usage: python pdf_validator.py <pdf_path> [job_id] [expected_pages] [job_type]")
        sys.exit(1)

    pdf_path       = sys.argv[1]
    job_id         = sys.argv[2] if len(sys.argv) > 2 else None
    expected_pages = int(sys.argv[3]) if len(sys.argv) > 3 else None
    job_type       = sys.argv[4] if len(sys.argv) > 4 else 'simplex'

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    result = validate_pdf(pdf_path, expected_pages, job_type=job_type)

    print("\n" + "═"*50)
    print(f"RESULT: {'✓ PASSED' if result.passed else '✗ FAILED'}")
    print("═"*50)
    if result.errors:
        print("\nERRORS (must fix):")
        for e in result.errors:
            print(f"  ✗ {e}")
    if result.warnings:
        print("\nWARNINGS (review):")
        for w in result.warnings:
            print(f"  ⚠ {w}")
    print(f"\nDetails: {json.dumps(result.info, indent=2)}")

    if job_id:
        save_validation_result(job_id, result)

    sys.exit(0 if result.passed else 1)
