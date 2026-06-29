"""
parser.py – PDF Parsing Layer
==============================
## Changes (Feature Update)
- Feature 7: Added pdfplumber table-extraction fallback (_extract_from_tables)
             When regex finds 0 rows, attempts to parse structured table cells instead.
             Improves parsing of lab PDFs that use native table layout.

Architecture Role: Layer 2 – Data Extraction Layer
Responsibility:
    - Accept a PDF file path or file bytes
    - Extract lab test rows using pdfplumber + regex (primary)
    - Fall back to pdfplumber table extraction for structured PDFs
    - Return a clean Pandas DataFrame with columns:
        [test_name, measured_value, unit, reference_range, raw_line]
"""

import re
import io
import logging
import pdfplumber
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns to capture common lab report row formats, e.g.:
#   "Hemoglobin    13.5 g/dL    12.0 – 17.5"
#   "WBC           6.2  K/μL    4.0-11.0"
#   "Fasting Glucose 95 mg/dL  70-99"
# ---------------------------------------------------------------------------
_ROW_PATTERN = re.compile(
    r"(?P<test_name>[A-Za-z][A-Za-z0-9\s\-/]+?)\s+"    # Test name
    r"(?P<value>\d+\.?\d*)\s*"                           # Numeric value
    r"(?P<unit>[a-zA-Z/%μ\*]+[^0-9\s]*?)?\s*"           # Optional unit
    r"(?P<ref_range>\d+\.?\d*\s*[-–]\s*\d+\.?\d*)",     # Reference range
    re.IGNORECASE,
)

# Loose numeric pattern used by table fallback
_NUMERIC = re.compile(r"^\d+\.?\d*$")
_RANGE   = re.compile(r"^\d+\.?\d*\s*[-–]\s*\d+\.?\d*$")

# Known test name aliases for normalisation
_TEST_ALIASES: dict[str, str] = {
    # Hemoglobin
    "hgb": "Hemoglobin",
    "hb": "Hemoglobin",
    "haemoglobin": "Hemoglobin",
    "haemoglobin level": "Hemoglobin",
    "hemoglobin level": "Hemoglobin",
    "hemoglobin (hb)": "Hemoglobin",
    "hemoglobin (hgb)": "Hemoglobin",
    # RBC
    "red blood cell": "RBC",
    "red blood cells": "RBC",
    "rbc count": "RBC",
    "total rbc": "RBC",
    "total rbc count": "RBC",
    "erythrocyte count": "RBC",
    "erythrocytes": "RBC",
    # WBC
    "white blood cell": "WBC",
    "white blood cells": "WBC",
    "wbc count": "WBC",
    "total wbc": "WBC",
    "total wbc count": "WBC",
    "leukocyte count": "WBC",
    "leukocytes": "WBC",
    # Platelets
    "platelet": "Platelets",
    "platelet count": "Platelets",
    "plt": "Platelets",
    "plt count": "Platelets",
    "thrombocyte count": "Platelets",
    "thrombocytes": "Platelets",
    # LDL
    "ldl cholesterol": "LDL",
    "ldl-c": "LDL",
    "ldl-cholesterol": "LDL",
    "low density lipoprotein": "LDL",
    # HDL
    "hdl cholesterol": "HDL",
    "hdl-c": "HDL",
    "hdl-cholesterol": "HDL",
    "high density lipoprotein": "HDL",
    # Fasting Glucose
    "glucose (fasting)": "Fasting Glucose",
    "fasting blood glucose": "Fasting Glucose",
    "glucose, fasting": "Fasting Glucose",
    "glucose fasting": "Fasting Glucose",
    "blood glucose (fasting)": "Fasting Glucose",
    "blood glucose fasting": "Fasting Glucose",
    "blood sugar fasting": "Fasting Glucose",
    "fbs": "Fasting Glucose",
    "fasting sugar": "Fasting Glucose",
    "glucose": "Fasting Glucose",
    "blood glucose": "Fasting Glucose",
    # Creatinine
    "creatinine (serum)": "Creatinine",
    "serum creatinine": "Creatinine",
    "creatinine, serum": "Creatinine",
    "creat": "Creatinine",
}

def _normalise_test_name(raw: str) -> str:
    """Normalise raw test name string to a canonical benchmark key."""
    cleaned = raw.strip().lower()
    return _TEST_ALIASES.get(cleaned, raw.strip().title())


def _extract_text(source) -> str:
    """
    Extract raw text from a pdfplumber source.
    Accepts:
        - str / Path   → file path
        - bytes / BytesIO → in-memory PDF bytes
    """
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)

    try:
        with pdfplumber.open(source) as pdf:
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
        return "\n".join(pages_text)
    except Exception as exc:
        logger.error("pdfplumber failed to open source: %s", exc)
        raise ValueError(f"Could not read PDF: {exc}") from exc


def _extract_from_tables(source) -> list:
    """
    Fallback: use pdfplumber table extraction for structured PDFs.
    Looks for rows with [test_name, numeric_value, unit?, range] patterns.
    Returns a list of row dicts matching the same schema as regex extraction.
    """
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)

    rows = []
    try:
        with pdfplumber.open(source) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        # Clean cells
                        cells = [str(c).strip() if c is not None else "" for c in row]
                        if len(cells) < 3:
                            continue

                        # Try to identify: test_name | value | [unit] | ref_range
                        test_name = cells[0]
                        if not test_name or not re.match(r"[A-Za-z]", test_name):
                            continue

                        # Find numeric value cell
                        val_cell = None
                        for c in cells[1:]:
                            if _NUMERIC.match(c.replace(",", ".")):
                                val_cell = c.replace(",", ".")
                                break
                        if val_cell is None:
                            continue

                        # Find range cell
                        range_cell = None
                        for c in cells[1:]:
                            if _RANGE.match(c.replace("–", "-").replace(" ", "")):
                                range_cell = c.replace("–", "-").strip()
                                break
                        if range_cell is None:
                            continue

                        # Unit is whatever is between value and range (optional)
                        unit = ""
                        vi = next((i for i, c in enumerate(cells) if c == val_cell), -1)
                        ri = next((i for i, c in enumerate(cells) if c == range_cell), -1)
                        if 0 <= vi < ri - 1:
                            unit = cells[vi + 1]

                        try:
                            measured_value = float(val_cell)
                        except ValueError:
                            continue

                        rows.append({
                            "test_name": _normalise_test_name(test_name),
                            "measured_value": measured_value,
                            "unit": unit,
                            "reference_range": range_cell,
                            "raw_line": " | ".join(cells),
                        })
    except Exception as exc:
        logger.warning("Table extraction fallback failed: %s", exc)

    return rows


def parse_pdf(source) -> pd.DataFrame:
    """
    Parse a lab report PDF and return a structured DataFrame.

    Parameters
    ----------
    source : str | Path | bytes | BytesIO
        PDF to parse.

    Returns
    -------
    pd.DataFrame
        Columns: test_name, measured_value, unit, reference_range, raw_line
        measured_value is cast to float; non-parseable rows are skipped.
    """
    # Keep a copy of source for the table fallback (BytesIO can only be read once)
    if isinstance(source, io.BytesIO):
        source_bytes = source.read()
        source = io.BytesIO(source_bytes)
        source_copy = io.BytesIO(source_bytes)
    else:
        source_copy = source

    raw_text = _extract_text(source)
    rows = []

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = _ROW_PATTERN.search(line)
        if match:
            test_name = _normalise_test_name(match.group("test_name"))
            raw_value = match.group("value")
            unit = (match.group("unit") or "").strip()
            ref_range = match.group("ref_range").replace("–", "-").strip()

            try:
                measured_value = float(raw_value)
            except ValueError:
                logger.warning("Could not cast value '%s' for test '%s'", raw_value, test_name)
                continue

            rows.append(
                {
                    "test_name": test_name,
                    "measured_value": measured_value,
                    "unit": unit,
                    "reference_range": ref_range,
                    "raw_line": line,
                }
            )

    # ── Feature 7 Fallback: pdfplumber table extraction ──────────────────
    if not rows:
        logger.info("Regex found 0 rows — attempting pdfplumber table extraction fallback…")
        rows = _extract_from_tables(source_copy)

    if not rows:
        logger.warning("No lab values extracted. PDF may use a non-standard format.")

    df = pd.DataFrame(
        rows,
        columns=["test_name", "measured_value", "unit", "reference_range", "raw_line"],
    )

    # De-duplicate: keep last occurrence of each test (some reports repeat headers)
    df = df.drop_duplicates(subset="test_name", keep="last").reset_index(drop=True)
    logger.info("Extracted %d lab test rows from PDF.", len(df))
    return df
