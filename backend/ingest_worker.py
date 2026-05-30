"""
Standalone ingestion worker — spawned as a subprocess by main.py.

Runs in its own process/memory space so an OOM kill doesn't take
the FastAPI server down with it.

Usage:
    python ingest_worker.py <pdf_path> <data_dir> <out_json_path>

Writes a JSON result file on completion (success or error).
"""
import json
import os
import sys

# Resolve paths and load .env before importing heavy deps
sys.path.insert(0, os.path.dirname(__file__))
_env = os.path.join(os.path.dirname(__file__), "..", ".env")
from dotenv import load_dotenv
load_dotenv(_env)

from ingestion import ingest  # noqa: E402 — must come after load_dotenv

pdf_path = sys.argv[1]
data_dir = sys.argv[2]
out_file = sys.argv[3]

try:
    chunk_count, index_name = ingest(pdf_path, data_dir)
    result = {"status": "done", "chunk_count": chunk_count, "index_name": index_name}
except Exception as exc:
    result = {"status": "failed", "error": str(exc)}

with open(out_file, "w") as fh:
    json.dump(result, fh)
