from __future__ import annotations
from pathlib import Path
import csv
from datetime import datetime

CSV_COLUMNS = [
    "bug_id","timestamp","test_type","workflow","severity","title","expected","actual","repro_steps","page_url",
    "console_errors","network_failures","trace_path","screenshot_path","video_path",
    "suspected_root_cause","code_location_guess","confidence","github_issue_url"
]

def write_bugs_csv(path: Path, bugs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for b in bugs:
            row = {k: b.get(k, "") for k in CSV_COLUMNS}
            if not row["timestamp"]:
                row["timestamp"] = datetime.utcnow().isoformat() + "Z"
            w.writerow(row)
