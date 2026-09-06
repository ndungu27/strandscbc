# KICD Curriculum Agent

An AI agent that turns "Grade 4, Agriculture, Conserving Water" into a
grounded Scheme of Work, Lesson Plan, and Assessment Rubric, using:

- **Strands Agents SDK** — agent loop and tool orchestration
- **Gemini API** — generation and embeddings
- **ChromaDB** — vector store of official KICD curriculum design content

## Project structure

```
kicd_agent/
├── requirements.txt      # dependencies
├── ingest.py             # Docling JSON -> sub-strand chunks -> ChromaDB
├── models.py             # Pydantic schemas: LessonPlan, SchemeOfWork, AssessmentRubric
├── agent.py              # the Strands agent, retrieval tool, main entry point
├── docling_json/         # <- put your Docling-extracted KICD JSON files here
└── kicd_chroma_db/       # created automatically by ingest.py (persistent vector store)
```

## Setup

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

export GEMINI_API_KEY=your_key_here    # Windows: set GEMINI_API_KEY=your_key_here
```

## Step 1 — Ingest your curriculum data

Put your Docling-extracted JSON files (from the earlier PDF extraction step)
into `docling_json/`, named so grade/subject can be guessed, e.g.
`grade4_agriculture_design.json`. Then:

```bash
python ingest.py
```

This will:
- parse each file into sub-strand-level chunks (strand, sub-strand, outcomes,
  learning experiences, key inquiry questions, PCIs, etc.)
- embed each chunk with Gemini's `text-embedding-004`
- store them in a persistent ChromaDB collection at `./kicd_chroma_db`

**Important:** the heading-matching regex in `ingest.py` (`HEADING_PATTERNS`)
is a best-effort match for common KICD document phrasing. After your first
run, open one of the printed chunk counts and spot-check a chunk against the
source PDF — if headings in your specific documents are phrased differently,
adjust the patterns before your demo.

## Step 2 — Run the agent

```bash
python agent.py "Grade 4, Agriculture, Conserving Water"
```

This will:
1. Call the `retrieve_kicd_content` tool against ChromaDB, filtered by grade
   and subject, ranked by semantic similarity to the topic
2. Draft a `LessonPlan`, `SchemeOfWork`, and `AssessmentRubric` as validated
   structured objects (not free-form text) using Gemini via Strands
3. Run a lightweight grounding check comparing retrieved KICD vocabulary
   against the generated lesson plan, flagging possible drift

If retrieval finds nothing for the grade/subject/topic given, the agent
refuses to draft rather than inventing curriculum content — try this on
purpose once before your demo so you have a "safe refusal" moment ready.

## Next steps (not included yet)

- **Document export:** convert the structured JSON output into a printable
  `.docx` (via `python-docx`) or PDF for teachers — the schemas in
  `models.py` map cleanly onto a Word template.
  Say the word and I'll build a `doc_generator.py` that fills a KICD-style
  scheme of work / lesson plan template from these structured objects.
- **Multi-lesson schemes:** `SchemeOfWork` currently generates from a single
  retrieval call; for a full-term scheme spanning multiple sub-strands,
  loop `retrieve_kicd_content` across each sub-strand in the strand and
  merge results before drafting.
- **Web/CLI front end:** wrap `plan_lesson()` in a simple Streamlit app or
  CLI menu so judges can type grade/subject/topic live during the demo.
