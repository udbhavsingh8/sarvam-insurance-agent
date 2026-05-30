"""
Direct integration test — calls the same Python functions the HTTP server uses,
without going through HTTP (so no server-timeout issues).

Tests:
  T2  STT  — saaras:v3 codemix  (already confirmed via HTTP)
  T3  TTS  — bulbul:v3 streaming (already confirmed via HTTP)
  T4  Ingestion — pdfplumber → OpenAI embeddings → FAISS save/load
  T5  LLM+RAG — sarvam-105b chat turn with retrieved context
"""
import sys, os, math, struct, wave, io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from dotenv import load_dotenv
load_dotenv()

PASS = "  ✅ "
FAIL = "  ❌ "

# ── T4: Ingestion ──────────────────────────────────────────────────
print("\nTest 4 — Ingestion (pdfplumber → OpenAI embeddings → FAISS)")
from ingestion import ingest, load_index

PDF = "/Users/ud/Desktop/Udbhav Resume IN.pdf"
import time
t0 = time.time()
chunk_count, index_name = ingest(PDF, "data")
elapsed = time.time() - t0

# Verify files on disk
assert os.path.exists(f"data/{index_name}.faiss"), "missing .faiss"
assert os.path.exists(f"data/{index_name}.pkl"),   "missing .pkl"

# Verify index loads and has correct vectors
idx, chunks = load_index("data", index_name)
assert idx.ntotal == chunk_count, f"index has {idx.ntotal} vecs, expected {chunk_count}"
print(f"{PASS}{chunk_count} chunks, {elapsed:.1f}s, index_name='{index_name}'")
print(f"      First chunk preview: {repr(chunks[0][:120])}")


# ── T4b: RAG retrieval ─────────────────────────────────────────────
print("\nTest 4b — RAG retrieval (FAISS cosine search)")
from rag import RAGRetriever

retriever = RAGRetriever("data", index_name)
results = retriever.retrieve("work experience skills")
assert len(results) > 0, "no results returned"
print(f"{PASS}{len(results)} chunks retrieved for 'work experience skills'")
print(f"      Top chunk preview: {repr(results[0][:120])}")


# ── T5: LLM + RAG chat turn ────────────────────────────────────────
print("\nTest 5 — LLM+RAG chat (sarvam-105b + FAISS context)")
from agent import AgentSession

session = AgentSession(retriever=retriever, mode="qa")
t0 = time.time()
reply = session.chat("What skills and experience does this person have?")
elapsed = time.time() - t0

assert reply and len(reply) > 20, f"reply too short: {repr(reply)}"
print(f"{PASS}Reply in {elapsed:.1f}s ({len(reply)} chars)")
print(f"\n{'─'*60}")
print(reply)
print(f"{'─'*60}\n")


# ── T5b: Summarize ────────────────────────────────────────────────
print("Test 5b — Session summary (sarvam-105b)")
t0 = time.time()
summary = session.summarize()
elapsed = time.time() - t0
assert summary and len(summary) > 20
print(f"{PASS}Summary in {elapsed:.1f}s ({len(summary)} chars)")
print(f"\n{summary}\n")


print("🎉  All direct tests passed — full pipeline verified.\n")
