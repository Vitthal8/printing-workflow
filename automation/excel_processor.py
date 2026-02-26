#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
PrintFlow Pro — Excel / CSV Data Processor
File: automation/excel_processor.py

PURPOSE:
  Validates and processes variable data files (Excel/CSV)
  used for mail merge and personalised printing jobs.

VALIDATIONS:
  ✓ Required columns present
  ✓ Record count
  ✓ Duplicate records detection
  ✓ Missing values in critical fields
  ✓ PIN code / postal code format
  ✓ Name field not blank
  ✓ Address completeness
  ✓ Data type consistency

INSTALL:
  pip install pandas openpyxl xlrd requests python-dotenv
═══════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

try:
    import pandas as pd
    PANDAS_OK = True
except ImportError:
    PANDAS_OK = False
    print("ERROR: pandas not installed. Run: pip install pandas openpyxl")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
# SCHEMA DEFINITIONS — required columns per job type
# ══════════════════════════════════════════════════════════════

# Core schema — required for ALL variable data jobs
CORE_REQUIRED_COLUMNS = [
    'name',         # Recipient name
    'address1',     # Address line 1
    'city',         # City
    'pincode',      # PIN code
]

# Optional but recommended columns
RECOMMENDED_COLUMNS = [
    'address2',     # Address line 2
    'state',        # State
    'account_no',   # Account / reference number
    'amount',       # Amount for statements
    'email',        # For digital notifications
    'mobile',       # For SMS
]

# Column aliases — common alternate names clients use
COLUMN_ALIASES = {
    'name':       ['recipient_name', 'customer_name', 'client_name', 'full_name', 'salutation'],
    'address1':   ['address', 'addr1', 'street', 'add1', 'address_line1'],
    'address2':   ['addr2', 'add2', 'address_line2', 'locality'],
    'city':       ['town', 'district', 'location'],
    'state':      ['province', 'st'],
    'pincode':    ['pin', 'zipcode', 'postal_code', 'pin_code', 'zip'],
    'account_no': ['account', 'acc_no', 'ref_no', 'reference', 'folio'],
    'amount':     ['value', 'balance', 'outstanding'],
}

# Indian PIN code pattern (6 digits, starts with 1-9)
PIN_PATTERN = r'^[1-9]\d{5}$'


# ══════════════════════════════════════════════════════════════
# PROCESSING RESULT
# ══════════════════════════════════════════════════════════════
class DataProcessingResult:
    def __init__(self, filename):
        self.filename         = filename
        self.passed           = True
        self.record_count     = 0
        self.column_count     = 0
        self.columns_found    = []
        self.columns_mapped   = {}   # original_name -> standard_name
        self.errors           = []
        self.warnings         = []
        self.stats            = {}
        self.sample_rows      = []   # first 3 rows for preview
        self.issues_by_column = {}

    def add_error(self, msg):
        self.errors.append(msg)
        self.passed = False
        log.error(f"  ✗ {msg}")

    def add_warning(self, msg):
        self.warnings.append(msg)
        log.warning(f"  ⚠ {msg}")

    def to_dict(self):
        return {
            'filename':          self.filename,
            'passed':            self.passed,
            'record_count':      self.record_count,
            'column_count':      self.column_count,
            'columns_found':     self.columns_found,
            'errors':            self.errors,
            'warnings':          self.warnings,
            'stats':             self.stats,
            'sample_rows':       self.sample_rows,
            'issues_by_column':  self.issues_by_column,
        }


# ══════════════════════════════════════════════════════════════
# COLUMN NORMALISATION
# ══════════════════════════════════════════════════════════════
def normalise_columns(df: pd.DataFrame) -> Dict[str, str]:
    """
    Map DataFrame columns to standard names using aliases.
    Returns dict: {original_col: standard_col}
    """
    mapping = {}
    df_cols_lower = {c.lower().strip().replace(' ', '_'): c for c in df.columns}

    for standard, aliases in COLUMN_ALIASES.items():
        # Check exact match first
        if standard in df_cols_lower:
            mapping[df_cols_lower[standard]] = standard
            continue
        # Check aliases
        for alias in aliases:
            if alias in df_cols_lower:
                mapping[df_cols_lower[alias]] = standard
                break

    return mapping


# ══════════════════════════════════════════════════════════════
# MAIN PROCESSOR
# ══════════════════════════════════════════════════════════════
def process_data_file(
    file_path: str,
    expected_count: Optional[int] = None,
    job_type: str = 'standard'
) -> DataProcessingResult:
    """
    Load and validate an Excel or CSV data file.

    Args:
        file_path:       Path to .xlsx, .xls, or .csv file
        expected_count:  Expected number of records (None = no check)
        job_type:        Job type for schema selection

    Returns:
        DataProcessingResult
    """
    result = DataProcessingResult(Path(file_path).name)
    log.info(f"Processing data file: {file_path}")

    if not Path(file_path).exists():
        result.add_error("File not found")
        return result

    # ── Load file ─────────────────────────────────────────────
    try:
        ext = Path(file_path).suffix.lower()
        if ext in ('.xlsx', '.xls'):
            df = pd.read_excel(file_path, dtype=str)
        elif ext == '.csv':
            # Try UTF-8 first, fall back to latin-1 (common in India)
            try:
                df = pd.read_csv(file_path, dtype=str, encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, dtype=str, encoding='latin-1')
        else:
            result.add_error(f"Unsupported file type: {ext}")
            return result

    except Exception as e:
        result.add_error(f"Could not open file: {str(e)}")
        return result

    # Strip whitespace from all string columns
    df = df.apply(lambda col: col.str.strip() if col.dtype == 'object' else col)
    # Drop completely empty rows
    df = df.dropna(how='all')

    result.record_count  = len(df)
    result.column_count  = len(df.columns)
    result.columns_found = list(df.columns)

    log.info(f"  Loaded: {result.record_count} rows, {result.column_count} columns")

    if result.record_count == 0:
        result.add_error("File contains no data rows")
        return result

    # ── Normalise column names ────────────────────────────────
    col_mapping = normalise_columns(df)
    result.columns_mapped = col_mapping

    # Rename to standard names
    df.rename(columns={orig: std for orig, std in col_mapping.items()}, inplace=True)

    # ── Check required columns ────────────────────────────────
    missing_required = [
        col for col in CORE_REQUIRED_COLUMNS
        if col not in df.columns
    ]
    if missing_required:
        result.add_error(
            f"Missing required columns: {', '.join(missing_required)}. "
            f"Found columns: {', '.join(result.columns_found[:8])}"
        )

    missing_recommended = [
        col for col in RECOMMENDED_COLUMNS
        if col not in df.columns
    ]
    if missing_recommended:
        result.add_warning(f"Recommended columns not found: {', '.join(missing_recommended)}")

    # ── Record count check ────────────────────────────────────
    if expected_count:
        diff = abs(result.record_count - expected_count)
        tolerance = max(10, expected_count * 0.01)  # 1% tolerance
        if diff > tolerance:
            result.add_error(
                f"Record count mismatch: expected {expected_count:,}, "
                f"found {result.record_count:,} (difference: {diff:,})"
            )
        else:
            log.info(f"  ✓ Record count: {result.record_count:,} (within tolerance)")

    # ── Duplicate check ───────────────────────────────────────
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        result.add_warning(f"{dup_count:,} duplicate rows detected. These will be printed twice unless removed.")
        result.stats['duplicates'] = int(dup_count)

    # Check duplicates on key identifier columns if present
    for id_col in ['account_no', 'mobile', 'email']:
        if id_col in df.columns:
            dups = df[id_col].dropna().duplicated().sum()
            if dups > 0:
                result.add_warning(f"{dups:,} duplicate values in '{id_col}' column")

    # ── Missing values analysis ───────────────────────────────
    for col in CORE_REQUIRED_COLUMNS:
        if col not in df.columns:
            continue
        null_count  = df[col].isna().sum() + (df[col] == '').sum()
        null_pct    = (null_count / result.record_count) * 100
        if null_count > 0:
            if null_pct > 5:
                result.add_error(
                    f"Column '{col}': {null_count:,} missing values ({null_pct:.1f}%). "
                    f"Critical field cannot have more than 5% blanks."
                )
            else:
                result.add_warning(f"Column '{col}': {null_count:,} missing values ({null_pct:.1f}%)")
            result.issues_by_column[col] = {
                'missing': int(null_count),
                'missing_pct': round(null_pct, 2)
            }

    # ── PIN code validation ───────────────────────────────────
    if 'pincode' in df.columns:
        valid_pins   = df['pincode'].dropna().str.match(PIN_PATTERN)
        invalid_pins = (~valid_pins).sum()
        if invalid_pins > 0:
            sample_invalid = df.loc[~df['pincode'].str.match(PIN_PATTERN, na=False), 'pincode'].head(5).tolist()
            result.add_warning(
                f"{invalid_pins:,} invalid PIN codes. "
                f"Sample: {sample_invalid}"
            )
            result.stats['invalid_pincodes'] = int(invalid_pins)

    # ── Name length check ─────────────────────────────────────
    if 'name' in df.columns:
        very_long = (df['name'].str.len() > 60).sum()
        if very_long > 0:
            result.add_warning(f"{very_long} names exceed 60 characters — may not fit in window envelope")

    # ── Address length check ──────────────────────────────────
    if 'address1' in df.columns:
        blank_addr = (df['address1'].isna() | (df['address1'] == '')).sum()
        if blank_addr > 0:
            result.add_error(f"{blank_addr:,} records have blank address line 1")

    # ── Stats summary ─────────────────────────────────────────
    result.stats.update({
        'total_records':   result.record_count,
        'clean_records':   result.record_count - df.duplicated().sum(),
        'columns':         result.column_count,
        'columns_mapped':  len(col_mapping),
        'completeness_pct': round(
            (1 - df[CORE_REQUIRED_COLUMNS].isnull().sum().sum() /
             (result.record_count * len(CORE_REQUIRED_COLUMNS))) * 100, 1
        ) if all(c in df.columns for c in CORE_REQUIRED_COLUMNS) else 0
    })

    # ── Sample rows for preview ───────────────────────────────
    try:
        preview_cols = [c for c in ['name','address1','city','pincode','account_no'] if c in df.columns]
        result.sample_rows = df[preview_cols].head(3).fillna('').to_dict('records')
    except Exception:
        pass

    status = "✓ PASSED" if result.passed else "✗ FAILED"
    log.info(f"Data validation {status} — {len(result.errors)} errors, {len(result.warnings)} warnings")
    return result


# ══════════════════════════════════════════════════════════════
# SAVE RESULT TO SUPABASE
# ══════════════════════════════════════════════════════════════
def save_result(job_id: str, result: DataProcessingResult):
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    headers = {
        'apikey': key, 'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json'
    }
    payload = {
        'record_count':           result.record_count,
        'data_validation_passed': result.passed,
        'data_errors':            json.dumps(result.errors),
        'data_warnings':          json.dumps(result.warnings),
        'data_stats':             json.dumps(result.stats),
        'status':                 'processing' if result.passed else 'error',
        'updated_at':             datetime.utcnow().isoformat()
    }
    requests.patch(
        f"{url}/rest/v1/jobs?id=eq.{job_id}",
        json=payload, headers=headers, timeout=10
    )
    log.info(f"Result saved for job {job_id}")


# ══════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    """
    Usage: python excel_processor.py <file_path> [expected_count] [job_id]

    Examples:
      python excel_processor.py data.xlsx
      python excel_processor.py statements.csv 14820
      python excel_processor.py merge_data.xlsx 22400 job-uuid-here
    """
    if len(sys.argv) < 2:
        print("Usage: python excel_processor.py <file_path> [expected_count] [job_id]")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    file_path      = sys.argv[1]
    expected_count = int(sys.argv[2]) if len(sys.argv) > 2 else None
    job_id         = sys.argv[3] if len(sys.argv) > 3 else None

    result = process_data_file(file_path, expected_count)

    print("\n" + "═"*55)
    print(f"RESULT: {'✓ PASSED' if result.passed else '✗ FAILED'}")
    print(f"Records: {result.record_count:,} | Columns: {result.column_count}")
    print("═"*55)
    if result.errors:
        print("\nERRORS (must fix before printing):")
        for e in result.errors: print(f"  ✗ {e}")
    if result.warnings:
        print("\nWARNINGS (review recommended):")
        for w in result.warnings: print(f"  ⚠ {w}")
    print(f"\nStats: {json.dumps(result.stats, indent=2)}")
    if result.sample_rows:
        print("\nSample records:")
        for row in result.sample_rows:
            print(f"  {row}")

    if job_id:
        save_result(job_id, result)

    sys.exit(0 if result.passed else 1)
