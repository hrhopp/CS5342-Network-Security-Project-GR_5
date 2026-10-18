"""Central settings for the Network-Security Tutor.

Every path, model name and tuning number lives here so there is exactly one
place to read or change it. Settings are added as each pipeline step needs
them; each one is commented with what it does and why it has that value.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Local-only guards (Step 9) -- applied as soon as any module imports config.
# ---------------------------------------------------------------------------
# Forced (not defaults), so a stray setting in someone's environment can't
# switch on a library feature that talks to the internet:
#   ANONYMIZED_TELEMETRY  ChromaDB usage analytics
#   LANGCHAIN_TRACING_V2 / LANGSMITH_TRACING  LangSmith cloud tracing of prompts
#   HF_HUB_OFFLINE        Hugging Face model downloads (Chroma's default embedder)
for _var, _value in {"ANONYMIZED_TELEMETRY": "False", "LANGCHAIN_TRACING_V2": "false",
                     "LANGSMITH_TRACING": "false", "HF_HUB_OFFLINE": "1"}.items():
    os.environ[_var] = _value

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Project root = the folder that contains rag/. Derived from this file's own
# location, so paths are correct no matter which directory Python is run from.
BASE_DIR = Path(__file__).resolve().parent.parent

# Course PDFs (slides, textbook, quizzes). Gitignored -- never committed.
RAW_DOCS_DIR = BASE_DIR / "docs" / "raw"

# Generated artifacts (hash manifest, vector DB). Gitignored -- never committed.
DATA_DIR = BASE_DIR / "data"

# ---------------------------------------------------------------------------
# Integrity gate (Step 2)
# ---------------------------------------------------------------------------
# Approved SHA-256 fingerprint of every ingested file. Lives in data/, so it is
# gitignored along with the vector DB.
MANIFEST_PATH = DATA_DIR / "manifest.json"

# Only these file types are hashed and ingested. Anything else in docs/raw is
# ignored (and reported), so a stray file can't slip into the knowledge base.
SUPPORTED_EXTENSIONS = {".pdf"}

# Bytes read per step while hashing. Does NOT affect the hash value -- only
# memory use and speed. 64 KiB keeps memory flat even for a 50 MB textbook
# while keeping the number of disk reads low. Sensible range: 4 KiB - 1 MiB.
HASH_BLOCK_SIZE = 64 * 1024

# ---------------------------------------------------------------------------
# Document loading (Step 3)
# ---------------------------------------------------------------------------
# "plain" follows the PDF's reading order and gives clean sentences.
# "layout" pads text with spaces to mimic the visual position on the slide,
# which preserves table columns but splits phrases with long gaps -- noise
# that hurts embeddings. Tested on our decks: plain reads better.
PDF_EXTRACTION_MODE = "plain"

# Pages with less extracted text than this are skipped (and reported).
# Catches title-only divider slides ("OSI Security Architecture", 25 chars)
# and diagram-only slides whose text is trapped in an image ("A Hyperledger",
# 13 chars). Such pages carry no answerable content but would still match
# queries on their title and waste a retrieval slot. Our shortest real
# content slide is 79 chars. Too high (>~150) drops short but real slides;
# too low (<~20) lets empty title slides through. Sensible range: 20-100.
MIN_PAGE_CHARS = 50

# ---------------------------------------------------------------------------
# Chunking (Step 4)
# ---------------------------------------------------------------------------
# doc_type comes from the subfolder of docs/raw a file sits in. Files anywhere
# else are rejected, so every chunk gets a known doc_type.
DOC_TYPE_FOLDERS = {"slides": "slides", "textbook": "textbook", "quizzes": "quiz"}

# doc_types the Q&A tutor may cite. "quiz" (past homework with student-written
# answers, some wrong) is left out: it is only for the quiz agent, via
# retrieve(..., doc_type="quiz"), never presented as authoritative course text.
QA_DOC_TYPES = ("slides", "textbook")

# Max characters per chunk (~1000 chars = ~170 words = ~250 tokens).
# Smaller than a textbook page, larger than any of our slides, so each slide
# stays one chunk and only long textbook pages are split.
# Bigger (e.g. 3000): one chunk mixes several topics -> blurrier vectors, and
#   4 retrieved chunks make a long prompt the CPU must read before answering.
# Smaller (e.g. 300): sentences lose the context that explains them.
# Sensible range: 500-2000.
CHUNK_SIZE = 1000

# Characters repeated between consecutive chunks of the same page, so a
# sentence cut at a boundary still appears whole in one of the two chunks.
# ~15% of CHUNK_SIZE. Bigger wastes storage and returns near-duplicate
# chunks; 0 risks splitting a key sentence in half. Range: 10-20% of size.
CHUNK_OVERLAP = 150

# ---------------------------------------------------------------------------
# Embeddings + vector store (Step 5)
# ---------------------------------------------------------------------------
# ChromaDB's on-disk folder (persist_directory). Inside data/, so it is
# gitignored, on the SSD, and outside OneDrive. It holds the full chunk text,
# so it is as sensitive as the PDFs.
CHROMA_DIR = DATA_DIR / "chroma"

# A collection is ChromaDB's equivalent of a table. One collection = one
# embedding model: vectors from different models can't be compared, so if
# EMBED_MODEL ever changes, use a new collection name and re-ingest.
COLLECTION_NAME = "netsec_course"

# How "closeness" between vectors is measured. Cosine compares the DIRECTION
# of two vectors and ignores their length, which is what text-embedding
# models are trained for. L2 (straight-line distance) also counts length.
# Fixed when the collection is created; changing it means re-ingesting.
DISTANCE_METRIC = "cosine"

# Numbers per vector produced by nomic-embed-text. Set by the model, not by
# us -- used to detect a wrong/swapped model before bad vectors are stored.
EMBED_DIM = 768

# Chunks sent to Ollama per request. Bigger batches mean fewer HTTP round
# trips (slightly faster) but more RAM per request and coarser progress
# updates; on CPU the model's math dominates either way. Range: 8-128.
EMBED_BATCH_SIZE = 32

# nomic-embed-text was trained with a task prefix telling it whether a text is
# a document to be found or a question doing the finding. Its model card says
# to always use them; mixing them up measurably weakens retrieval.
EMBED_DOC_PREFIX = "search_document: "
EMBED_QUERY_PREFIX = "search_query: "

# ---------------------------------------------------------------------------
# Retrieval (Step 6)
# ---------------------------------------------------------------------------
# Chunks fetched per question (n_results). 4 x ~250 tokens = ~1000 tokens of
# context: enough for a definition plus supporting detail, small enough that
# the CPU reads the prompt quickly and the 3B model doesn't lose focus.
# Bigger (8+): slower answers, more off-topic text for the model to wade
# through. Smaller (1-2): one bad match leaves nothing useful. Range: 3-6.
TOP_K = 4

# Cosine DISTANCE thresholds (0 = same direction, 1 = unrelated, 2 = opposite).
# Calibrated on our data: in-course questions scored a best distance of
# 0.21-0.32, out-of-course questions (capital of France, cake recipe, World
# Cup) 0.37-0.47.
#
# Gate: if even the BEST chunk is farther than this, the question isn't
# covered by the course -> refuse without calling the LLM.
# Too low (0.25): real questions get refused. Too high (0.45): off-topic
# questions get "answered" from loosely related chunks.
RELEVANCE_GATE = 0.35

# Per-chunk cutoff once the gate has passed: weaker supporting chunks up to
# this distance are still passed to the LLM; anything farther is dropped.
# Must be >= RELEVANCE_GATE. Range: gate to gate + 0.1.
MAX_DISTANCE = 0.40

# ---------------------------------------------------------------------------
# Ollama (local model server)
# ---------------------------------------------------------------------------
# Loopback address only. Hard-coded rather than read from an environment
# variable so nothing can silently redirect prompts to a remote machine.
# 127.0.0.1 rather than "localhost": on Windows "localhost" may resolve to the
# IPv6 address ::1 first, but Ollama listens on IPv4 127.0.0.1.
OLLAMA_BASE_URL = "http://127.0.0.1:11434"

# Refuse to start if the model server address is ever edited to a non-local
# host: prompts contain course text, so they must never cross the network.
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
if urlparse(OLLAMA_BASE_URL).hostname not in LOOPBACK_HOSTS:
    raise RuntimeError(f"OLLAMA_BASE_URL must be a loopback address, got {OLLAMA_BASE_URL}")

LLM_MODEL = "llama3.2:3b"          # writes answers (Steps 7-8)
EMBED_MODEL = "nomic-embed-text"   # turns text into 768-number vectors (Steps 5-6)

# ---------------------------------------------------------------------------
# LLM generation (Step 7)
# ---------------------------------------------------------------------------
# Randomness when picking each next token. 0 = always the most likely token
# (repeatable, sticks to the text); 1 = creative, more prone to inventing.
# A tutor citing course material wants near-deterministic answers.
# Range for factual Q&A: 0.0-0.3. (The quiz agent may want ~0.7 for variety.)
LLM_TEMPERATURE = 0.1

# Context window: the most tokens the model can see at once (system prompt +
# retrieved chunks + question + its own answer). Our prompts use ~1,500.
# Set explicitly because when a prompt is too long Ollama silently drops the
# OLDEST tokens -- the system prompt with our security rules goes first.
# Bigger costs RAM and CPU time; llama3.2 supports up to 128k. Range: 4k-8k.
LLM_NUM_CTX = 4096

# max_tokens: hard cap on answer length (~300 words). On CPU every generated
# token costs time, so this bounds the worst-case wait. Too low cuts answers
# mid-sentence. Range: 200-800.
LLM_MAX_TOKENS = 400

# How long Ollama keeps the model in RAM after a request. Reloading 2 GB from
# disk adds several seconds to the next question; 30 min covers a demo.
LLM_KEEP_ALIVE = "30m"

# ---------------------------------------------------------------------------
# Q&A agent (Step 8)
# ---------------------------------------------------------------------------
# Longer questions are rejected: they waste context-window space and are a
# common carrier for long injection payloads. ~80 words is plenty for a
# course question. Range: 300-1000.
MAX_QUESTION_CHARS = 500

# The exact sentence the model must use when the excerpts don't answer the
# question. Fixed wording lets the code detect a refusal reliably.
REFUSAL_MESSAGE = "I can't find this in the course materials."

# Shown instead of a response that the output filter blocked.
BLOCKED_MESSAGE = "I can't share that. Please ask a question about the course material."

# Appended to the refusal shown to the student when the course doesn't cover a
# question (not to what the model must say, which has to stay exact).
REFUSAL_HINT = "Turn on web search, or look it up with a search engine."

# ---------------------------------------------------------------------------
# Web search (the ONE deliberate exception to local-only)
# ---------------------------------------------------------------------------
# Used only when the user turns it on AND the course has nothing relevant, or
# for "learn more" links in quiz feedback. Only the user's question is sent,
# over HTTPS; course text, chunks and embeddings never are. Result pages are
# never opened: titles, URLs and snippets come back in the search response
# itself, so the search services below are the only external hosts contacted.
#
# Search services, tried in order until one returns results. DuckDuckGo
# rate-limits automated queries ("No results found" for minutes at a time),
# so Wikipedia's search API is the fallback; it needs keyword queries, which
# web.search derives from the question. Neither needs an API key, so there is
# no key to store or leak (threat T3). If a keyed API is ever added, read the
# key from .env (gitignored). These are the only external hosts contacted.
WEB_BACKENDS = ("duckduckgo", "wikipedia")

# Results per lookup. Each snippet goes into the prompt, so 3 x ~1000 chars
# stays well inside the context window. Range: 2-5.
WEB_MAX_RESULTS = 3

# Web text is the most likely source of injected instructions, so each snippet
# is capped (on top of redaction). Range: 300-1500.
WEB_SNIPPET_CHARS = 1000

# Longest query sent out. Shorter than MAX_QUESTION_CHARS: a long query is
# more likely to carry pasted course text off the machine. Range: 100-300.
WEB_QUERY_MAX_CHARS = 200

# Seconds before a lookup is abandoned (e.g. Wi-Fi off). Range: 5-20.
WEB_TIMEOUT = 10

# Local record of every lookup (time, query, result hosts), so internet use is
# visible and auditable. In data/, so it is gitignored and owner-only.
WEB_AUDIT_LOG = DATA_DIR / "web_audit.log"


def ensure_dirs() -> None:
    """Create the working folders if missing (e.g. on a fresh clone)."""
    for d in (RAW_DOCS_DIR, DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
