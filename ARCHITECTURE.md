# RAG System Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│               LOCAL RAG: NETWORK-SECURITY TUTOR & QUIZ BOT          │
│     LangChain · Ollama (llama3.2:3b + nomic-embed-text) · ChromaDB  │
│             Everything runs on 127.0.0.1, nothing leaves the PC     │
└─────────────────────────────────────────────────────────────────────┘
```

The interactive diagram is in [`architecture-diagram.mmd`](architecture-diagram.mmd). Open it in
VS Code with a Mermaid extension or paste it into https://mermaid.live/ (only the diagram source,
never course text). GitHub renders it automatically.

## High-Level Architecture

```
┌──────────────────┐
│     Student      │
│ (Streamlit UI)   │   ◄── teammate
└────────┬─────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            AGENT LAYER                              │
│  ┌──────────────────────────┐        ┌───────────────────────────┐  │
│  │   Q&A Tutor Agent        │        │   Quiz Agent  (teammate)  │  │
│  │   rag/qa.py              │        │                           │  │
│  │ - answer(question)       │        │ - MCQ / True-False /      │  │
│  │ - slides + textbook only │        │   open-ended              │  │
│  │ - mandatory citations    │        │ - grading + feedback      │  │
│  └────────────┬─────────────┘        └─────────────┬─────────────┘  │
└───────────────┼────────────────────────────────────┼────────────────┘
                └─────────────────┬──────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     RETRIEVAL LAYER  rag/retriever.py               │
│                                                                     │
│   retrieve(question, k=4, doc_type=None | "slides" | [..])          │
│        │                                                            │
│        ├─ embed question  ("search_query: " prefix, 768 dims)       │
│        ├─ ChromaDB nearest neighbours (cosine, HNSW)                │
│        ├─ best distance > 0.35 ?  ──► return []  (refuse, no LLM)   │
│        └─ keep chunks with distance ≤ 0.40                          │
│                                                                     │
│   RetrievedChunk {text, source, page, doc_type, sha256, distance,   │
│                   .similarity, .citation}                           │
└──────────────────────────────────┬──────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│               PROMPT SECURITY + GENERATION  rag/qa.py, rag/llm.py   │
│                                                                     │
│   1. Redact instruction-like sentences in chunks                    │
│   2. Wrap chunks as UNTRUSTED DATA between random per-request       │
│      markers <<<COURSE_DATA_xxxx>>>, label them [S1]..[S4]          │
│   3. System rules (with hidden canary) + reminder after the data    │
│   4. Ollama llama3.2:3b on 127.0.0.1:11434                          │
│      temperature 0.1 · context 4096 tokens · max 400 tokens         │
│   5. Output filter: rules text / canary / markers / secrets         │
│        └─ leak ──► "blocked" message                                │
│   6. Refusal detection                                              │
│   7. [S1] ──► "(Lecture 1, slide 5)" built from metadata by code    │
└──────────────────────────────────┬──────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          PRESENTATION                               │
│   Answer {text, citations, chunks, refused, blocked, seconds,       │
│           suspicious_sources}  ──► CLI (rag.qa) or Streamlit UI     │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. Ingestion Flow (`python -m rag.integrity` then `python -m rag.vectorstore`)
```
docs/raw/{slides,textbook,quizzes}/*.pdf
    │
    ├─► integrity.py   SHA-256 of every file vs data/manifest.json
    │        ├─ new        → recorded (approved)
    │        ├─ unchanged  → ok
    │        └─ changed    → REFUSE whole run (exit 1), human must --accept
    │
    ├─► loader.py      PyPDFLoader, one Document per page
    │        ├─ page = PDF index + 1
    │        ├─ glyph names (/uni2295) decoded, PDF's own metadata discarded
    │        └─ pages under 50 chars skipped (title-only / image-only)
    │
    ├─► chunker.py     re-hash file (TOCTOU), RecursiveCharacterTextSplitter
    │        ├─ 1000 chars, 150 overlap, never across pages
    │        ├─ id = sha256[:16]-p{page}-c{i}  (deterministic → no duplicates)
    │        └─ metadata {source, page, doc_type, sha256}
    │
    ├─► embeddings.py  nomic-embed-text via Ollama, "search_document: " prefix,
    │                  batches of 32, dimension check (768)
    │
    └─► vectorstore.py ChromaDB upsert into data/chroma/ (collection netsec_course)
             ├─ skip chunks already stored with identical text
             ├─ re-embed chunks whose text changed
             └─ purge chunks of removed / replaced files
```

### 2. Q&A Tutor Flow (`python -m rag.qa`)
```
Question
    │
    ├─ empty / > 500 chars / no letters  → refuse immediately
    │
    ▼
retrieve(question, doc_type=("slides", "textbook"))
    │
    ├─ nothing close enough → "I can't find this in the course materials." (< 1 s)
    │
    ▼
build_prompt  →  generate (llama3.2:3b, ~20–40 s on CPU)
    │
    ├─ leak_reason() → blocked
    ├─ refusal shape → refused (no fake sources)
    │
    ▼
attach_citations → Answer(text, citations, ...)
```

### 3. Quiz Agent Flow (teammate, using this pipeline)
```
Topic (or random topic)
    │
    ▼
retrieve(topic, k=6, doc_type="slides")      ← lecture content
retrieve(topic, doc_type="quiz")             ← past homework, style examples only
    │
    ▼
generate(user=..., system=..., temperature=0.7)  → questions + answers + chunk citation
    │
    ▼
Student answers → grading → feedback with citation ("Prev Lecture 13, slide 4")
```

## Component Details

### Storage Layer
```
┌─────────────────────────────────────────────┐
│  FILE SYSTEM  (gitignored, owner-only ACL)  │
├─────────────────────────────────────────────┤
│  docs/raw/                                  │
│   ├─ slides/    26 lecture decks            │
│   ├─ textbook/  3 textbooks                 │
│   └─ quizzes/   3 past homeworks            │
│                                             │
│  data/                                      │
│   ├─ manifest.json   approved SHA-256s      │
│   └─ chroma/         ChromaDB (SQLite+HNSW) │
└─────────────────────────────────────────────┘
```

### Vector Database (ChromaDB)
```
┌─────────────────────────────────────────────┐
│  CHROMADB COLLECTION: netsec_course         │
├─────────────────────────────────────────────┤
│  Configuration:                             │
│    - PersistentClient, in-process (no port) │
│    - HNSW index, cosine distance            │
│    - embedding_function=None (we embed via  │
│      Ollama; Chroma's downloader disabled)  │
│    - telemetry off, reset disabled          │
│    - metadata embed_model guard             │
│                                             │
│  Entry:                                     │
│    id:        "be4fa2f6acc0de33-p5-c0"      │
│    document:  chunk text (≤ 1000 chars)     │
│    embedding: 768 floats                    │
│    metadata:  {source, page,                │
│                doc_type, sha256}            │
│                                             │
│  Operations:                                │
│    - upsert(): batches of 32                │
│    - query():  top-4 + where doc_type       │
│    - get():    diffing on re-ingest         │
└─────────────────────────────────────────────┘
```

### LLM Integration (Ollama)
```
┌─────────────────────────────────────────────┐
│  OLLAMA LOCAL MODELS                        │
├─────────────────────────────────────────────┤
│  Endpoint: http://127.0.0.1:11434           │
│  (code refuses any non-loopback URL)        │
│                                             │
│  Chat model:  llama3.2:3b  (~2.0 GB)        │
│    - temperature: 0.1                       │
│    - num_ctx:     4096 tokens               │
│    - num_predict: 400 tokens                │
│    - keep_alive:  30 min                    │
│                                             │
│  Embedding model: nomic-embed-text (274 MB) │
│    - 768 dimensions                         │
│    - task prefixes search_document: /       │
│      search_query:                          │
└─────────────────────────────────────────────┘
```

## Technology Stack

```
┌─────────────────────┬──────────────────────────────────┐
│  LAYER              │  TECHNOLOGY                      │
├─────────────────────┼──────────────────────────────────┤
│  Orchestration      │  LangChain 1.4                   │
│  PDF loading        │  PyPDFLoader (pypdf 6.20 +       │
│                     │  fonttools)                      │
│  Text splitting     │  RecursiveCharacterTextSplitter  │
│  Embeddings         │  nomic-embed-text via Ollama     │
│  Vector database    │  ChromaDB 1.5.9                  │
│  LLM                │  llama3.2:3b via Ollama          │
│  Integrity          │  SHA-256 (hashlib)               │
│  Frontend UI        │  Streamlit (teammate)            │
│  Language           │  Python 3.10.11                  │
└─────────────────────┴──────────────────────────────────┘
```

## Key Features

### 1. Grounded answers only
- The model may only use the retrieved course excerpts.
- A calibrated relevance gate refuses off-topic questions **before** the LLM runs.

### 2. Citation accuracy
- The model only writes `[S1]` labels. Code turns them into citations from chunk metadata,
  so a citation can never point to a page that wasn't retrieved.
- Invented labels are dropped, and a Sources list is always attached.

### 3. Defense in depth against prompt injection
| Layer | Stops |
|---|---|
| Relevance gate | Off-topic and probing questions never reach the model |
| Redaction | "Ignore previous instructions…" hidden inside documents |
| Random markers + UNTRUSTED DATA labelling | Documents pretending to end the data block |
| System rules + reminder after data | Small model forgetting the rules |
| Output filter (7-gram overlap, canary, markers) | System prompt leaks |
| Secret patterns + env-value check | Key and token leaks |
| Code-built citations | Fake citations |

### 4. Knowledge-base integrity
- Every file is fingerprinted. If an approved file changes by a single bit, the run is refused.

## Performance Characteristics

```
┌───────────────────────┬──────────────────────────────────┐
│  OPERATION            │  TIME (i7-1165G7, CPU only)      │
├───────────────────────┼──────────────────────────────────┤
│  Full first ingest    │  ~35 min (6,089 chunks, once)    │
│  Re-ingest            │  only new / changed files        │
│  Vector search        │  < 1 s                           │
│  Off-topic refusal    │  < 1 s (LLM not called)          │
│  Answer               │  20–40 s (+10 s first load)      │
└───────────────────────┴──────────────────────────────────┘
```

## Security & Privacy

- **Local only:** Ollama runs on loopback, ChromaDB runs in-process, and telemetry,
  LangSmith tracing and Hugging Face downloads are forced off in `config.py`.
- **Verified:** `python -m rag.security_check --egress` watches network connections during a real
  question. The bot also works with Wi-Fi off.
- **Data at rest:** `data/` and `docs/raw/` are readable only by the owner, SYSTEM and
  Administrators (`--harden`).
- **Git:** course PDFs, the vector DB and `.env` files are gitignored, and `security_check`
  verifies this.

## Error Handling

```
┌────────────────────────────┬───────────────────────────────────────┐
│  FAILURE POINT             │  BEHAVIOUR                            │
├────────────────────────────┼───────────────────────────────────────┤
│  Approved PDF modified     │  Ingest refused, file named, exit 1   │
│  File swapped mid-ingest   │  IntegrityError (re-hash mismatch)    │
│  PDF in wrong folder       │  Error naming the allowed folders     │
│  Empty knowledge base      │  Clear message, no fake refusal       │
│  Question not in course    │  Refusal, LLM not called              │
│  Model leaks rules         │  Response blocked                     │
│  Embedding model changed   │  Collection refuses to open           │
│  Non-loopback Ollama URL   │  RuntimeError at import               │
│  Ollama not running        │  Connection refused → run ollama serve│
└────────────────────────────┴───────────────────────────────────────┘
```
