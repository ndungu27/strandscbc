"""
KICD Curriculum Agent
======================
Given a teacher's request like "Grade 4, Agriculture, Conserving Water",
this agent:
  1. Retrieves the official KICD sub-strand content from ChromaDB
     (grounded -- never invents outcomes/PCIs)
  2. Drafts a Scheme of Work, Lesson Plan, and Assessment Rubric using
     Gemini via the Strands SDK, constrained to the Pydantic schemas
     in models.py

Usage:
    export GEMINI_API_KEY=your_key_here
    python agent.py "Grade 4, Agriculture, Conserving Water"
"""

import os
import sys

import chromadb
from gemini_embedding import GeminiEmbeddingFunction
from strands import Agent, tool
from strands.models.gemini import GeminiModel
from dotenv import load_dotenv
load_dotenv()

from models import LessonPlan, SchemeOfWork, AssessmentRubric

CHROMA_DB_PATH = "./kicd_chroma_db"
COLLECTION_NAME = "kicd_curriculum"

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("Set the GEMINI_API_KEY environment variable first.")
    sys.exit(1)

# --- ChromaDB setup -------------------------------------------------------

client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
gemini_ef = GeminiEmbeddingFunction(api_key=api_key)
collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=gemini_ef,
    )

# --- Tools ------------------------------------------------------------------

@tool
def retrieve_kicd_content(grade: str, subject: str, topic: str) -> str:
    """Retrieve the official KICD strand, sub-strand, learning outcomes,
    suggested learning experiences, key inquiry question(s), core
    competencies, and Pertinent and Contemporary Issues (PCIs) for a given
    grade, subject, and topic from the curriculum design database.

    Always call this BEFORE drafting a scheme of work, lesson plan, or
    rubric. Do not draft anything using content that was not returned by
    this tool -- if it returns no results, tell the user rather than
    inventing curriculum content.

    Args:
        grade: e.g. "Grade 4"
        subject: e.g. "Agriculture"
        topic: the sub-strand topic, e.g. "Conserving Water"
    """
    results = _collection.query(
        query_texts=[topic],
        n_results=3,
        where={"$and": [{"grade": grade}, {"subject": subject}]},
    )
    documents = results.get("documents", [[]])[0]
    if not documents:
        return (
            f"NO KICD CONTENT FOUND for grade='{grade}', subject='{subject}', "
            f"topic='{topic}'. Do not fabricate outcomes or PCIs. Tell the "
            f"user to check the grade/subject/topic spelling, or that this "
            f"curriculum design has not been ingested yet."
        )
    return "\n\n---\n\n".join(documents)


# --- Agent setup --------------------------------------------------------

_model = GeminiModel(
    client_args={"api_key": API_KEY},
    model_id="gemini-3.1-flash-lite",
    params={"temperature": 0.3, "max_output_tokens": 4096},
)

SYSTEM_PROMPT = """You are a curriculum planning assistant for Kenyan CBC
(Competency-Based Curriculum) teachers, built on official KICD curriculum
designs.

Rules you must always follow:
1. Before drafting anything, call retrieve_kicd_content with the grade,
   subject, and topic the teacher gave you.
2. Base every specific learning outcome, key inquiry question, core
   competency, value, and PCI ONLY on what retrieve_kicd_content returns.
   Never invent or assume curriculum content that wasn't retrieved.
3. If retrieval finds nothing, say so plainly and ask the teacher to check
   the grade/subject/topic -- do not draft a plan anyway.
4. Keep language practical and classroom-ready; a teacher should be able to
   use your output with little to no editing.
5. Make sure PCIs are woven meaningfully into learning experiences, not just
   listed as a label.
"""

agent = Agent(
    model=_model,
    tools=[retrieve_kicd_content],
    system_prompt=SYSTEM_PROMPT,
)


# --- Grounding check -----------------------------------------------------

def grounding_check(generated_text: str, retrieved_text: str, min_overlap: float = 0.15) -> bool:
    """Cheap anti-hallucination signal: what fraction of distinctive words
    in the retrieved KICD content also appear in the generated output.
    Not a rigorous metric -- just a fast sanity check to flag drift for
    manual review, e.g. in a hackathon demo."""
    def words(t: str) -> set:
        return {w.lower() for w in t.split() if len(w) > 5}

    retrieved_words = words(retrieved_text)
    generated_words = words(generated_text)
    if not retrieved_words:
        return True
    overlap = len(retrieved_words & generated_words) / len(retrieved_words)
    return overlap >= min_overlap


# --- Main entry point -----------------------------------------------------

def plan_lesson(grade: str, subject: str, topic: str):
    """Runs the full pipeline: retrieve -> draft scheme of work, lesson
    plan, and rubric as validated structured objects."""

    retrieved = retrieve_kicd_content(grade=grade, subject=subject, topic=topic)
    if retrieved.startswith("NO KICD CONTENT FOUND"):
        print(retrieved)
        return None

    print("--- Retrieved KICD content ---")
    print(retrieved[:600], "...\n")

    base_prompt = (
        f"Using ONLY this official KICD content:\n\n{retrieved}\n\n"
        f"Draft a {{artifact}} for {grade} {subject}, topic '{topic}'."
    )

    lesson_plan = agent.structured_output(
        LessonPlan, prompt=base_prompt.format(artifact="single lesson plan")
    )
    scheme_of_work = agent.structured_output(
        SchemeOfWork,
        prompt=base_prompt.format(
            artifact="4-lesson scheme of work covering this sub-strand across a term"
        ),
    )
    rubric = agent.structured_output(
        AssessmentRubric, prompt=base_prompt.format(artifact="assessment rubric")
    )

    is_grounded = grounding_check(lesson_plan.model_dump_json(), retrieved)
    print(f"Grounding check on lesson plan: {'PASS' if is_grounded else 'REVIEW NEEDED'}\n")

    return {
        "lesson_plan": lesson_plan,
        "scheme_of_work": scheme_of_work,
        "rubric": rubric,
        "grounded": is_grounded,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python agent.py "Grade 4, Agriculture, Conserving Water"')
        sys.exit(1)

    raw = sys.argv[1]
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 3:
        print('Please format as: "Grade, Subject, Topic" e.g. "Grade 4, Agriculture, Conserving Water"')
        sys.exit(1)

    grade_in, subject_in, topic_in = parts
    result = plan_lesson(grade_in, subject_in, topic_in)

    if result:
        print("=== LESSON PLAN ===")
        print(result["lesson_plan"].model_dump_json(indent=2))
        print("\n=== SCHEME OF WORK ===")
        print(result["scheme_of_work"].model_dump_json(indent=2))
        print("\n=== RUBRIC ===")
        print(result["rubric"].model_dump_json(indent=2))
