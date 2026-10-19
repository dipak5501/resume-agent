from pydantic import BaseModel


class ImproveResult(BaseModel):
    tex: str
    changed: bool
    changes: list[str] = []  # human-readable "what changed"
    summary: str = ""  # 2-3 line brief of what THIS pass did — rides the same LLM call
    added: list[str] = []  # skills/projects/claims newly added — the user's review list
    compiled: bool
    single_page: bool
    warnings: list[str] = []
