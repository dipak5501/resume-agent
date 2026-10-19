"""Answer-bank CRUD (T13). Seeded canonical-core rows are edited (answer+mode);
custom Q&A rows are created/deleted freely. Single profile, like T11."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Answer
from app.routers.profile import PID
from app.schemas.answer import AnswerIn, AnswerOut

router = APIRouter()


def _get(db: Session, aid: str) -> Answer:
    a = db.get(Answer, aid)
    if a is None or a.profile_id != PID:
        raise HTTPException(status_code=404, detail="answer not found")
    return a


@router.get("/answers")
def list_answers(db: Session = Depends(get_db)) -> list[AnswerOut]:
    rows = db.scalars(select(Answer).where(Answer.profile_id == PID).order_by(Answer.created_at))
    return [AnswerOut.model_validate(a) for a in rows]


@router.post("/answers")
def create_answer(body: AnswerIn, db: Session = Depends(get_db)) -> AnswerOut:
    if not (body.question or "").strip():
        raise HTTPException(status_code=400, detail="custom answer needs a question")
    a = Answer(profile_id=PID, canonical=None, question=body.question, answer=body.answer, mode=body.mode)
    db.add(a)
    db.commit()
    return AnswerOut.model_validate(a)


@router.put("/answers/{aid}")
def update_answer(aid: str, body: AnswerIn, db: Session = Depends(get_db)) -> AnswerOut:
    a = _get(db, aid)
    a.answer, a.mode = body.answer, body.mode
    if a.canonical is None and body.question is not None:  # custom rows keep their editable question
        a.question = body.question
    db.commit()
    return AnswerOut.model_validate(a)


@router.delete("/answers/{aid}")
def delete_answer(aid: str, db: Session = Depends(get_db)) -> dict:
    a = _get(db, aid)
    if a.canonical is not None:  # seeded core stays put (re-seeded on init); only custom is deletable
        raise HTTPException(status_code=400, detail="canonical-core answers can't be deleted, only cleared")
    db.delete(a)
    db.commit()
    return {"ok": True}
