"""Autofill field-mapping endpoint (T12 Phase 2). Takes structure-only field
descriptors, returns canonical mappings (cache → heuristic → LLM). No values in,
no values out — mapping only."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.answer import AnswerRequest, AnswerResult
from app.schemas.autofill import AutofillCorrectIn, AutofillMapIn, AutofillMapOut
from app.services import answerer, field_map

router = APIRouter()


@router.post("/autofill/map")
def autofill_map(body: AutofillMapIn, db: Session = Depends(get_db)) -> AutofillMapOut:
    return AutofillMapOut(mappings=field_map.resolve(body.host, body.fields, db))


@router.post("/autofill/correct")
def autofill_correct(body: AutofillCorrectIn, db: Session = Depends(get_db)) -> dict:
    """T19 learning loop: a user correction upserts the (host, form_sig) cache so
    the next run serves it. Structure + corrected canonical only — never a value."""
    field_map.correct(body.host, body.fields, body.field_ref, body.corrected_canonical, db)
    return {"ok": True}


@router.post("/autofill/answer")
def autofill_answer(body: AnswerRequest, db: Session = Depends(get_db)) -> AnswerResult:
    """Answer one screening question (T13). Body carries only question + job_id +
    host — never the user's other filled data or page HTML."""
    return answerer.answer(body.question, body.job_id, body.host, db)
