"""
End-to-end integration tests against the running FastAPI server.
Tests 2-5 from the agreed list (Test 1 /health already passed).
Run with:  .venv/bin/python run_tests.py
"""

import sys
import time
import httpx

BASE = "http://127.0.0.1:8000"
client = httpx.Client(timeout=120)  # long timeout for embedding calls


def ok(label):
    print(f"  ✅  {label}")

def fail(label, detail):
    print(f"  ❌  {label}: {detail}")
    sys.exit(1)


# ── Test 2: STT /transcribe ────────────────────────────────────────
print("\nTest 2 — STT /transcribe (saaras:v3 codemix)")
import wave, struct, math

samples = [int(32767 * math.sin(2 * math.pi * 440 * t / 16000)) for t in range(16000)]
import io
buf = io.BytesIO()
with wave.open(buf, "w") as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
    wf.writeframes(struct.pack("<" + "h" * len(samples), *samples))
wav_bytes = buf.getvalue()

r = client.post(f"{BASE}/transcribe",
    files={"audio": ("test.wav", wav_bytes, "audio/wav")},
    data={"language_code": "en-IN"})
if r.status_code != 200:
    fail("transcribe", f"HTTP {r.status_code}: {r.text}")
data = r.json()
if "transcript" not in data:
    fail("transcribe", f"no 'transcript' key: {data}")
ok(f"transcript returned (sine wave → empty string is correct): '{data['transcript']}'")


# ── Test 3: TTS /speak ────────────────────────────────────────────
print("\nTest 3 — TTS /speak (bulbul:v3 streaming, en-IN)")
r = client.get(f"{BASE}/speak",
    params={"text": "Namaste! Welcome to our insurance plan.", "language_code": "en-IN"})
if r.status_code != 200:
    fail("speak", f"HTTP {r.status_code}: {r.text}")
wav = r.content
if not wav.startswith(b"RIFF"):
    fail("speak", f"response is not a WAV (first bytes: {wav[:8].hex()})")
ok(f"WAV audio received: {len(wav):,} bytes, header={wav[:4]}")

# Also test hi-IN
r2 = client.get(f"{BASE}/speak",
    params={"text": "नमस्ते! हमारी बीमा योजना में आपका स्वागत है।", "language_code": "hi-IN"})
if r2.status_code != 200:
    fail("speak hi-IN", f"HTTP {r2.status_code}: {r2.text}")
ok(f"hi-IN WAV audio received: {len(r2.content):,} bytes")


# ── Test 4: /upload  PDF → chunks → embeddings → FAISS ───────────
print("\nTest 4 — /upload (pdfplumber text extraction → txt file)")
PDF = "/Users/ud/sarvam-insurance-agent/data/Lic-leaflet-jeevan-Anand-4-5x8-inches-wxh-DEC-2020-(1).pdf"
with open(PDF, "rb") as f:
    pdf_bytes = f.read()

t0 = time.time()
r = client.post(f"{BASE}/upload",
    files={"file": ("lic_policy.pdf", pdf_bytes, "application/pdf")},
    data={"mode": "qa"})

if r.status_code != 200:
    fail("upload", f"HTTP {r.status_code}: {r.text}")
data = r.json()
job_id = data.get("job_id")
if not job_id:
    fail("upload", f"no job_id in response: {data}")
print(f"  ℹ️  job_id={job_id[:8]}… — polling /status/{job_id[:8]}… (up to 300s, Terminal window will open for ingestion)")

# Poll until done or failed
poll_client = httpx.Client(timeout=10)
while True:
    time.sleep(3)
    pr = poll_client.get(f"{BASE}/status/{job_id}")
    if pr.status_code != 200:
        fail("status poll", f"HTTP {pr.status_code}: {pr.text}")
    job = pr.json()
    status = job.get("status")
    elapsed = time.time() - t0
    print(f"  … {elapsed:.0f}s — status={status}", end="\r", flush=True)
    if status == "done":
        print()
        break
    if status == "failed":
        fail("upload/ingest", job.get("error", "unknown error"))
    if elapsed > 310:
        fail("upload/ingest", "timed out waiting for ingestion after 310s")
poll_client.close()

session_id = job.get("session_id")
chunk_count = job.get("chunk_count", 0)
if not session_id:
    fail("upload", f"no session_id in completed job: {job}")
if chunk_count == 0:
    fail("upload", "chunk_count is 0")
ok(f"Ingested {chunk_count} chunks in {elapsed:.1f}s → session_id={session_id[:8]}…")


# ── Test 5: /chat  LLM + RAG round-trip ──────────────────────────
print("\nTest 5 — /chat (sarvam-105b + FAISS RAG)")
r = client.post(f"{BASE}/chat",
    data={
        "session_id": session_id,
        "message": "What experience does this person have?",
        "stream": "false",
    })
if r.status_code != 200:
    fail("chat", f"HTTP {r.status_code}: {r.text}")
data = r.json()
reply = data.get("reply", "")
if not reply:
    fail("chat", f"empty reply: {data}")
ok(f"LLM reply ({len(reply)} chars):\n\n{reply}\n")


print("\n🎉  All 5 tests passed — end-to-end pipeline verified.\n")
client.close()
