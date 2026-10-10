"""Convert IndiaMART call-log exports into the replayer's input format.

Usage::

    python3 data/process_indiamart_csv.py input.csv data/sample_calls.csv

The export contains spreadsheet-style numeric values (for example ``123.0``)
and timestamps with minute precision.  IDs are normalized so sticky routing
uses the same caller key on every replay.
"""

import csv
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional


OUTPUT_FIELDS = [
    "call_id",
    "caller_id",
    "call_duration_sec",
    "call_duration_observed",
    "disposition",
    "meeting_fixed",
    "recording_url",
]


def normalize_identifier(value: Optional[str]) -> str:
    """Return a stable string identifier without CSV/spreadsheet float noise."""
    value = (value or "").strip()
    if not value or value.lower() in {"0", "0.0", "nan", "none"}:
        return ""
    if re.fullmatch(r"[+-]?\d+\.0+", value):
        return value.split(".", 1)[0]
    return value


def parse_call_duration(row: Dict[str, str]) -> Optional[float]:
    """Read only an explicit duration field; record timestamps are not call length."""
    for key in ("call_duration_sec", "call_duration_seconds", "duration_seconds", "call_duration"):
        raw = (row.get(key) or "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
            if math.isfinite(value) and value >= 0:
                return value
        except ValueError:
            continue
    return None


def transform_indiamart_row(row: Dict[str, str], index: int) -> Dict[str, Any]:
    caller_id = normalize_identifier(row.get("fk_glusr_usr_id"))
    if not caller_id:
        caller_id = normalize_identifier(row.get("modrefid"))
    if not caller_id:
        caller_id = f"user_{index + 1}"

    call_id = normalize_identifier(row.get("fk_leap_call_records_id")) or f"call_{index + 1}"

    remarks = (row.get("disposition_remarks") or "").strip()
    remarks = remarks or "No Information"

    # These are the successful business outcomes in the IndiaMART export.
    is_converted = int(bool(re.search(r"\bbl\s+(approved|enriched|generated)\b", remarks, re.I)))

    duration_sec = parse_call_duration(row)
    duration_observed = duration_sec is not None

    recording_url = row.get("call_recording_url", "").strip()

    return {
        "call_id": call_id,
        "caller_id": caller_id,
        "call_duration_sec": duration_sec,
        "call_duration_observed": int(duration_observed),
        "disposition": remarks,
        "meeting_fixed": is_converted,
        "recording_url": recording_url
    }

def process_indiamart_csv(input_csv_path: str, output_csv_path: str) -> int:
    processed = []
    with open(input_csv_path, mode="r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            processed.append(transform_indiamart_row(row, i))

    output_path = Path(output_csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open(mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(processed)

    converted = sum(row["meeting_fixed"] for row in processed)
    rate = converted / len(processed) if processed else 0.0
    print(
        f"Processed {len(processed)} calls ({converted} BL outcomes, "
        f"{rate:.1%}) into {output_path}"
    )
    return len(processed)

if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "data/raw_indiamart_calls.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/sample_calls.csv"
    process_indiamart_csv(inp, out)
