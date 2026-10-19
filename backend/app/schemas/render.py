from pathlib import Path

from pydantic import BaseModel


class Guards(BaseModel):
    compiles: bool
    extraction_clean: bool
    single_page: bool


class RenderResult(BaseModel):
    ok: bool
    pdf_path: Path | None
    page_count: int | None
    text: str
    guards: Guards
    errors: list[str] = []
