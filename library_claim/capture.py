"""M02a file-import/reopen CLI. Browser camera transport is M02b."""

import argparse
from pathlib import Path

from .capture_store import CaptureInput, FrameStore


def main():
    parser = argparse.ArgumentParser(description="Durable original-frame evidence store")
    parser.add_argument("--store", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--file", type=Path, required=True)
    ingest.add_argument("--sweep-id", required=True)
    ingest.add_argument("--upload-id", required=True)
    ingest.add_argument("--captured-at", required=True, help="Caller-supplied ISO timestamp with timezone")
    ingest.add_argument("--media-sequence", required=True, type=int)
    ingest.add_argument("--synthetic", action="store_true")
    reopen = commands.add_parser("reopen")
    reopen.add_argument("--frame-id", required=True)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--sweep-id", required=True)
    args = parser.parse_args()
    store = FrameStore(args.store)
    if args.command == "ingest":
        capture = CaptureInput(sweep_id=args.sweep_id, upload_id=args.upload_id,
                               captured_at=args.captured_at, media_sequence=args.media_sequence,
                               source="file_import", synthetic=args.synthetic)
        record = store.ingest_file(capture, args.file)
        store.write_manifest(args.sweep_id)
        print(record.model_dump_json(indent=2))
    elif args.command == "reopen":
        print(store.get(args.frame_id).model_dump_json(indent=2))
    else:
        print(store.write_manifest(args.sweep_id))


if __name__ == "__main__":
    main()
