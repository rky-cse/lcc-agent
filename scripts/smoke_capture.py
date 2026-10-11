"""Synthetic M02a CLI restart smoke. Run from the repository root."""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise FileExistsError("choose a fresh smoke output directory")
    root.mkdir(parents=True)
    original = root / "synthetic-original.png"
    image = Image.new("RGB", (2048, 1536), "#deeaf4")
    draw = ImageDraw.Draw(image)
    draw.text((64, 64), "SYNTHETIC M02a STORAGE FIXTURE - no real shelf or room", fill="black")
    for x in range(64, 1900, 100):
        draw.rectangle((x, 200, x + 60, 1300), outline="navy", width=4)
    image.save(original)
    expected_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    command = [sys.executable, "-B", "-m", "library_claim.capture", "--store", str(root / "store")]
    result = subprocess.run(command + ["ingest", "--file", str(original), "--sweep-id", "synthetic-m02a",
                            "--upload-id", "original-1", "--captured-at", datetime.now(timezone.utc).isoformat(),
                            "--media-sequence", "0", "--synthetic"], check=True, capture_output=True, text=True)
    saved = json.loads(result.stdout)
    # The importing process has exited. A separate interpreter verifies/reopens it.
    result = subprocess.run(command + ["reopen", "--frame-id", saved["id"]],
                            check=True, capture_output=True, text=True)
    reopened = json.loads(result.stdout)
    assert saved == reopened
    assert reopened["sha256"] == expected_hash
    assert (reopened["width"], reopened["height"]) == (2048, 1536)
    assert (root / "store" / reopened["path"]).read_bytes() == original.read_bytes()
    record_path = root / "reopened-frame.json"
    record_path.write_text(json.dumps(reopened, indent=2) + "\n", encoding="utf-8")
    print(f"Synthetic restart smoke passed: {record_path}")
    print(f"Preserved original: {root / 'store' / reopened['path']}")


if __name__ == "__main__":
    main()
