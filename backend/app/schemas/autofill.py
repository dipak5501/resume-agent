"""Autofill mapping contract (T12 Phase 2). The request carries ONLY field
structure — labels, attributes, types — never a filled value and never page
HTML. This is the privacy trust boundary; keep FieldDescriptor structural."""

from typing import Literal

from pydantic import BaseModel


class FieldDescriptor(BaseModel):
    field_ref: int
    tag: str = ""
    type: str = ""
    name: str = ""
    id: str = ""
    autocomplete: str = ""
    aria_label: str = ""
    placeholder: str = ""
    label: str = ""
    data_automation_id: str = ""  # Workday's primary field signal (structure, not a value)
    required: bool = False
    # T19: structure-only nearby signal (enclosing heading/legend text) for the
    # LLM lane. Labels/headings only — never a filled value (privacy boundary).
    context: str = ""


class AutofillMapIn(BaseModel):
    host: str
    fields: list[FieldDescriptor]


class FieldMappingOut(BaseModel):
    field_ref: int
    canonical: str
    confidence: float
    source: Literal["cache", "heuristic", "llm"]


class AutofillMapOut(BaseModel):
    mappings: list[FieldMappingOut]


class AutofillCorrectIn(BaseModel):
    """A user correction (T19 learning loop). Carries the field STRUCTURE (so the
    server recomputes the SAME form_sig as /map) + the canonical the user's action
    revealed — NEVER the value. Upserts the FieldMapping cache so the next run on
    this form is right, deterministically."""

    host: str
    fields: list[FieldDescriptor]  # structure only — same privacy boundary as /map
    field_ref: int
    corrected_canonical: str
