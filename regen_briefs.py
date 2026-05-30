"""
Regenerate advisor briefs for all ingested documents in data/.

Run this once after upgrading to the LLM-generated brief (Phase B).
Rewrites every *.brief.txt file using the new LLM approach.

Usage:
    .venv/bin/python3 regen_briefs.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from ingestion import _generate_product_profile, load_document, load_metadata

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

docs = [
    f[:-len(".meta.json")]
    for f in os.listdir(DATA_DIR)
    if f.endswith(".meta.json")
]

if not docs:
    print("No ingested documents found in data/")
    sys.exit(0)

print(f"Found {len(docs)} document(s): {docs}\n")

for name in docs:
    print(f"Regenerating brief for: {name} ... ", end="", flush=True)
    try:
        text = load_document(DATA_DIR, name)
        meta = load_metadata(DATA_DIR, name)
        brief = _generate_product_profile(text, meta)
        brief_path = os.path.join(DATA_DIR, f"{name}.brief.txt")
        with open(brief_path, "w", encoding="utf-8") as fh:
            fh.write(brief)
        source = "LLM" if "COVERAGE:" in brief and len(brief) > 400 else "keyword fallback"
        print(f"done ({len(brief)} chars, {source})")
    except Exception as e:
        print(f"FAILED: {e}")

print("\nAll done. Restart the server to pick up new briefs.")
