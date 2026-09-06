"""
Structured output schemas for the KICD agent's generated artifacts.
Using Pydantic models with Agent.structured_output() forces Gemini to return
a validated, consistently-shaped object instead of free-form text.
"""

from typing import List
from pydantic import BaseModel, Field


class LessonPlan(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    week: int = Field(description="Week number within the term/scheme")
    lesson_number: int = Field(description="Lesson number within the week")
    specific_learning_outcomes: List[str] = Field(
        description="Verbatim or lightly adapted from the KICD sub-strand outcomes"
    )
    key_inquiry_question: str
    core_competencies: List[str]
    pcis: List[str] = Field(description="Pertinent and Contemporary Issues addressed")
    values: List[str]
    organisation_of_learning: dict = Field(
        description="Keys: 'introduction', 'lesson_development', 'conclusion' -- "
                     "each a short paragraph of teacher/learner activities"
    )
    resources: List[str]
    assessment_methods: List[str]
    reflection: str = Field(
        default="",
        description="Blank space/prompt for the teacher's post-lesson reflection"
    )


class SchemeOfWorkEntry(BaseModel):
    week: int
    lesson_number: int
    strand: str
    sub_strand: str
    specific_learning_outcomes: List[str]
    key_inquiry_question: str
    learning_experiences: List[str]
    core_competencies: List[str]
    pcis: List[str]
    resources: List[str]
    assessment_methods: List[str]
    reflection: str = Field(default="")


class SchemeOfWork(BaseModel):
    grade: str
    subject: str
    term: str = Field(description="e.g. 'Term 1'")
    entries: List[SchemeOfWorkEntry]


class RubricLevel(BaseModel):
    level_name: str = Field(description="e.g. 'Exceeds Expectation'")
    description: str


class RubricCriterion(BaseModel):
    criterion: str = Field(description="e.g. 'Explains the importance of conserving water'")
    levels: List[RubricLevel] = Field(
        description="Typically 4 levels: Exceeds / Meets / Approaches / Below Expectation"
    )


class AssessmentRubric(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    criteria: List[RubricCriterion]
