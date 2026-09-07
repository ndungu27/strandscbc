"""
Ingest KICD curriculum design JSON (extracted via Docling) into ChromaDB.

KICD curriculum designs are TABLE-based, not heading-paragraph based.
Confirmed structure (from inspect_json.py output on a real KICD file):

  - "Curriculum" tables: 5 columns
      Strand | Sub strand | Specific learning outcomes |
      Suggested learning experiences | Suggested Key inquiry question(s)
    One data row = one sub-strand.

  - "Rubric" tables: 5 columns
      Level Indicator | Exceeds Expectations | Meets Expectations |
      Approaches Expectations | Below Expectations
    These appear right after the curriculum table(s) for a strand, but do
    NOT contain the strand name themselves -- we attribute each rubric
    table to whichever strand most recently appeared, based on document
    order. If a document interleaves these unusually, spot-check the
    output.

  - "Assessment" tables: 4 columns
      Strand | Suggested Assessment Methods | Suggested Learning Resources |
      Suggested Non-formal Activities
    These DO contain the strand name per row, so they're merged back onto
    the matching curriculum chunk(s) by strand-name match.

KNOWN GAP: Pertinent and Contemporary Issues (PCIs) and Core Competencies
do not appear as their own table columns in the sample inspected. They may
exist as body text elsewhere in the document. This script does NOT
fabricate them -- each chunk's "pcis" and "core_competencies" metadata
fields are left empty, and the agent's system prompt should be told not to
claim PCIs came from KICD unless they were actually retrieved. If you find
PCIs elsewhere in your documents (e.g. a dedicated table or heading),
tell me the pattern and I'll add extraction for it.

Usage:
    1. Docling JSON files go in "docling_json/"
    2. Set GEMINI_API_KEY (via .env or environment variable)
    3. python ingest.py
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import chromadb
from gemini_embedding import GeminiEmbeddingFunction

DOCLING_JSON_DIR = Path("docling_json")
CHROMA_DB_PATH = "./kicd_chroma_db"
COLLECTION_NAME = "kicd_curriculum"

GRADE_SUBJECT_PATTERN = re.compile(r"^([A-Z][A-Za-z\s\-]+?)\s+GRADE\s+(\d+)\s*$")
LESSON_COUNT_PATTERN = re.compile(r"\((\d+)\s*lessons?\)", re.IGNORECASE)


def cell_text(cell: dict) -> str:
    return (cell.get("text") or "").strip()


def get_grid(table: dict) -> list[list[dict]]:
    return table.get("data", {}).get("grid", [])


def get_page_no(item: dict) -> int:
    prov = item.get("prov") or []
    return prov[0].get("page_no", 0) if prov else 0


def classify_table(headers: list[str]) -> str:
    h = [x.lower() for x in headers]
    joined = " | ".join(h)
    if "strand" in joined and "sub strand" in joined and "specific learning outcomes" in joined:
        return "curriculum"
    if "level indicator" in joined and "exceeds expectations" in joined:
        return "rubric"
    if "strand" in joined and "suggested assessment methods" in joined:
        return "assessment"
    return "other"


def extract_grade_subject(doc_dict: dict, filename: str) -> tuple[str, str]:
    """Look for a 'SUBJECT GRADE N' section header near the start of the
    document (this is how KICD title pages are formatted). Falls back to
    a filename guess if not found -- check the printed result either way,
    since a wrong grade/subject silently breaks retrieval filtering later."""
    for item in doc_dict.get("texts", [])[:15]:
        if item.get("label") != "section_header":
            continue
        text = item.get("text", "").strip()
        m = GRADE_SUBJECT_PATTERN.match(text)
        if m:
            subject = m.group(1).strip().title()
            grade = f"Grade {m.group(2)}"
            return grade, subject

    # Fallback: guess from filename
    stem = Path(filename).stem
    grade_m = re.search(r"grade[\s\-_]*(\d+)", stem, re.IGNORECASE)
    grade = f"Grade {grade_m.group(1)}" if grade_m else "Unknown"
    subject_guess = re.sub(r"grade[\s\-_]*\d+", "", stem, flags=re.IGNORECASE)
    subject_guess = re.sub(r"[\-_]+", " ", subject_guess).strip().title() or "Unknown"
    print(f"  (!) Could not find 'SUBJECT GRADE N' header text -- "
          f"guessed '{grade}' / '{subject_guess}' from filename. Verify this.")
    return grade, subject_guess


def parse_curriculum_tables(doc_dict: dict) -> list[dict]:
    """Returns one dict per sub-strand row, in document order, tagged with
    the table's page number for later rubric attribution."""
    rows = []
    for table in doc_dict.get("tables", []):
        grid = get_grid(table)
        if not grid:
            continue
        headers = [cell_text(c) for c in grid[0]]
        kind = classify_table(headers)
        if kind != "curriculum":
            continue

        page_no = get_page_no(table)
        for data_row in grid[1:]:
            if len(data_row) < 5:
                continue
            strand = cell_text(data_row[0])
            sub_strand = cell_text(data_row[1])
            if not strand or not sub_strand:
                continue
            lesson_m = LESSON_COUNT_PATTERN.search(sub_strand)
            rows.append({
                "strand": strand,
                "sub_strand": sub_strand,
                "num_lessons": lesson_m.group(1) if lesson_m else "",
                "specific_learning_outcomes": cell_text(data_row[2]),
                "suggested_learning_experiences": cell_text(data_row[3]),
                "key_inquiry_question": cell_text(data_row[4]),
                "page_no": page_no,
                "assessment_methods": "",
                "learning_resources": "",
                "non_formal_activities": "",
                "rubric_text": "",
            })
    return rows


def parse_assessment_tables(doc_dict: dict) -> dict[str, dict]:
    """Returns {strand_name_lower: {assessment_methods, learning_resources,
    non_formal_activities}} keyed by strand text as it appears in the
    assessment table (matched case-insensitively against curriculum rows
    later)."""
    by_strand = {}
    for table in doc_dict.get("tables", []):
        grid = get_grid(table)
        if not grid:
            continue
        headers = [cell_text(c) for c in grid[0]]
        if classify_table(headers) != "assessment":
            continue
        for data_row in grid[1:]:
            if len(data_row) < 4:
                continue
            strand = cell_text(data_row[0])
            if not strand:
                continue
            by_strand[strand.lower()] = {
                "assessment_methods": cell_text(data_row[1]),
                "learning_resources": cell_text(data_row[2]),
                "non_formal_activities": cell_text(data_row[3]),
            }
    return by_strand


def parse_rubric_tables_in_order(doc_dict: dict) -> list[tuple[int, str]]:
    """Returns [(page_no, rubric_text), ...] in document order. Rubric
    tables don't carry a strand name, so we attribute them to the nearest
    PRECEDING curriculum strand by page number during merging."""
    rubrics = []
    for table in doc_dict.get("tables", []):
        grid = get_grid(table)
        if not grid:
            continue
        headers = [cell_text(c) for c in grid[0]]
        if classify_table(headers) != "rubric":
            continue
        page_no = get_page_no(table)
        lines = [" | ".join(headers)]
        for data_row in grid[1:]:
            lines.append(" | ".join(cell_text(c) for c in data_row))
        rubrics.append((page_no, "\n".join(lines)))
    return rubrics


def attach_rubrics(curriculum_rows: list[dict], rubrics: list[tuple[int, str]]) -> None:
    """For each rubric, attach it to every curriculum row whose strand
    matches the most recent curriculum row appearing before that rubric's
    page. In practice: find the curriculum row with the largest page_no
    that is <= the rubric's page_no, then attach to all rows sharing that
    row's strand."""
    if not curriculum_rows:
        return
    for rubric_page, rubric_text in rubrics:
        candidates = [r for r in curriculum_rows if r["page_no"] <= rubric_page]
        anchor = max(candidates, key=lambda r: r["page_no"]) if candidates else curriculum_rows[0]
        target_strand = anchor["strand"]
        for row in curriculum_rows:
            if row["strand"] == target_strand and not row["rubric_text"]:
                row["rubric_text"] = rubric_text


def attach_assessment(curriculum_rows: list[dict], assessment_by_strand: dict[str, dict]) -> None:
    for row in curriculum_rows:
        info = assessment_by_strand.get(row["strand"].lower())
        if info:
            row["assessment_methods"] = info["assessment_methods"]
            row["learning_resources"] = info["learning_resources"]
            row["non_formal_activities"] = info["non_formal_activities"]


def build_chunks(grade: str, subject: str, source_file: str, curriculum_rows: list[dict]) -> list[dict]:
    chunks = []
    for row in curriculum_rows:
        chunk_id = re.sub(
            r"[^a-z0-9]+", "_",
            f"{grade}_{subject}_{row['strand']}_{row['sub_strand']}".lower()
        ).strip("_")

        text_parts = [
            f"Grade: {grade}",
            f"Subject: {subject}",
            f"Strand: {row['strand']}",
            f"Sub-strand: {row['sub_strand']}",
            f"Specific Learning Outcomes: {row['specific_learning_outcomes']}",
            f"Suggested Learning Experiences: {row['suggested_learning_experiences']}",
            f"Key Inquiry Question: {row['key_inquiry_question']}",
        ]
        if row["assessment_methods"]:
            text_parts.append(f"Suggested Assessment Methods: {row['assessment_methods']}")
        if row["learning_resources"]:
            text_parts.append(f"Suggested Learning Resources: {row['learning_resources']}")
        if row["non_formal_activities"]:
            text_parts.append(f"Suggested Non-formal Activities: {row['non_formal_activities']}")
        if row["rubric_text"]:
            text_parts.append(f"Assessment Rubric:\n{row['rubric_text']}")

        chunks.append({
            "id": chunk_id,
            "text": "\n".join(text_parts),
            "metadata": {
                "grade": grade,
                "subject": subject,
                "strand": row["strand"],
                "sub_strand": row["sub_strand"],
                "num_lessons": row["num_lessons"],
                "source_page": row["page_no"],
                "source_file": source_file,
                "has_rubric": bool(row["rubric_text"]),
                "has_assessment_info": bool(row["assessment_methods"]),
                # Known gap -- see module docstring. Left empty rather than guessed.
                "pcis": "",
                "core_competencies": "",
            }
        })
    return chunks


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set. Check your .env file has GEMINI_API_KEY=... "
              "(no quotes) and that ingest.py is in the same folder as .env.")
        sys.exit(1)

    if not DOCLING_JSON_DIR.exists():
        print(f"'{DOCLING_JSON_DIR}' not found. Put your Docling JSON exports there.")
        sys.exit(1)

    json_files = sorted(DOCLING_JSON_DIR.glob("*.json"))
    if not json_files:
        print(f"No JSON files found in '{DOCLING_JSON_DIR}'.")
        sys.exit(0)

    all_chunks = []
    for jf in json_files:
        with open(jf, encoding="utf-8") as f:
            doc_dict = json.load(f)

        grade, subject = extract_grade_subject(doc_dict, jf.name)

        curriculum_rows = parse_curriculum_tables(doc_dict)
        assessment_by_strand = parse_assessment_tables(doc_dict)
        rubrics = parse_rubric_tables_in_order(doc_dict)

        attach_assessment(curriculum_rows, assessment_by_strand)
        attach_rubrics(curriculum_rows, rubrics)

        chunks = build_chunks(grade, subject, jf.name, curriculum_rows)
        print(f"{jf.name}: {grade} / {subject} -> {len(chunks)} sub-strand chunk(s), "
              f"{len(rubrics)} rubric table(s) found, "
              f"{len(assessment_by_strand)} strand(s) with assessment info")

        if not chunks:
            print(f"  !! No curriculum tables matched in {jf.name}. "
                  f"Run inspect_json.py on this specific file -- its table headers "
                  f"may be phrased differently than the sample this script was built from.")

        all_chunks.extend(chunks)

    if not all_chunks:
        print("\nNo chunks produced across any file. Nothing to ingest.")
        sys.exit(1)

    print(f"\nTotal chunks to ingest: {len(all_chunks)}")

    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    gemini_ef = GeminiEmbeddingFunction(api_key=api_key)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=gemini_ef,
    )

    batch_size = 20
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        collection.upsert(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
        print(f"  Upserted {i + len(batch)}/{len(all_chunks)}")

        time.sleep(15)

    print(f"\nDone. Collection '{COLLECTION_NAME}' now has {collection.count()} chunk(s) "
          f"stored at {CHROMA_DB_PATH}")


if __name__ == "__main__":
    main()