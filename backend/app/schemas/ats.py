from typing import Literal

from pydantic import BaseModel


class JdKeyword(BaseModel):
    term: str
    aliases: list[str] = []
    required: bool


class Requirement(BaseModel):
    """One thing a screener checks, in the JD's words (T34)."""

    text: str
    priority: Literal["must", "should"]


class RequirementVerdict(Requirement):
    verdict: Literal["meets", "unclear", "not_met"]
    evidence: str = ""  # a verbatim résumé quote; only kept when it really is in the résumé


class AtsScore(BaseModel):
    overall: int  # 0-100
    keyword_coverage: float  # fraction of required keywords matched, 0-1
    llm_fit: int  # 0-100: the requirement score (T34), from the verdicts below
    required_keywords: list[str]
    matched: list[str]
    missing: list[str]  # required JD keywords absent from the résumé — the gap list
    rationale: str
    requirements: list[RequirementVerdict] = []  # T34: per-requirement verdict + evidence
