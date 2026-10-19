"""3-tier hybrid field mapping (T12 Phase 2). Resolve each form field to a
canonical key by: cache (host+form_sig) → deterministic heuristic → one LLM call
for the remainder → write the result back to the cache. The LLM discovers, the
cache promotes. The LLM only MAPS labels; values always come from the profile,
client-side (see extension/src/content/plan.ts)."""

import hashlib
import re

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canonical import CANONICAL
from app.models import FieldMapping
from app.schemas.autofill import FieldDescriptor, FieldMappingOut
from app.services import llm

HIGH = 0.95  # native signal (autocomplete / input type / file)
KEYWORD = 0.85  # label/name keyword match

# Mirrors extension/src/content/mapper.ts. The mapper-parity test feeds one
# shared fixture set to both impls and fails if they drift (extension is canonical).
_AUTOCOMPLETE = {
    "name": "full_name",
    "given-name": "first_name",
    "family-name": "last_name",
    "email": "email",
    "tel": "phone",
    "tel-national": "phone",
}
_RULES = [
    ("first_name", re.compile(r"\b(first[\s_-]*name|given[\s_-]*name|forename|f[\s_-]?name)\b")),
    ("last_name", re.compile(r"\b(last[\s_-]*name|family[\s_-]*name|surname|l[\s_-]?name)\b")),
    ("email", re.compile(r"\be[\s_-]?mail\b")),
    ("phone", re.compile(r"\b(phone|mobile|cell|telephone|tel)\b")),
    ("linkedin", re.compile(r"linked[\s_-]?in")),
    ("github", re.compile(r"git[\s_-]?hub")),
    ("portfolio", re.compile(r"portfolio")),
    ("website", re.compile(r"\b(website|personal site|blog|homepage|url)\b")),
    ("work_authorization", re.compile(r"(work[\s_-]*authoriz|authoriz(ed|ation)\s*to\s*work|right\s*to\s*work|sponsor|visa|work permit|legally.*work)")),
    ("years_experience", re.compile(r"(years?[\s_-]*of[\s_-]*experience|years?[\s_-]*experience|experience.*years|total experience)")),
    ("cover_letter", re.compile(r"cover[\s_-]*letter")),
    ("location", re.compile(r"\b(city|location|where.*located|current location|based in)\b")),
    # T19: granular address subfields — detected but NEVER filled (profile has only a coarse location),
    # so a "Postal Code"/"Address Line"/"State"/"Country" field can't inherit the city value.
    ("address", re.compile(r"\b(street|address|postal|post\s*code|zip|state|province|county|country)\b")),
    ("full_name", re.compile(r"\b(full[\s_-]*name|your[\s_-]*name|legal[\s_-]*name|applicant[\s_-]*name|candidate[\s_-]*name)\b")),
]

# Workday keys fields off data-automation-id (camelCase/underscore compounds);
# match the normalized id by substring since word-boundary rules miss them.
_AUTOMATION_ID = [
    ("firstname", "first_name"),
    ("lastname", "last_name"),
    ("legalnamesectionname", "full_name"),
    ("email", "email"),
    ("phone", "phone"),
    ("linkedin", "linkedin"),
    ("github", "github"),
    ("city", "location"),
    ("coverletter", "cover_letter"),
]


def heuristic_map(f: FieldDescriptor) -> tuple[str, float] | None:
    """Deterministic classifier. Returns (canonical, confidence) or None when it
    can't confidently classify (→ the LLM lane handles it)."""
    tag, typ = f.tag.lower(), f.type.lower()
    hay = " ".join([f.name, f.id, f.aria_label, f.placeholder, f.label, f.data_automation_id]).lower()
    aid = re.sub(r"[^a-z]", "", f.data_automation_id.lower())  # normalize camelCase/underscores

    if typ == "file":
        if "cover" in hay:
            return "cover_letter", HIGH
        # Only a field that reads like the résumé slot gets the résumé. A generic
        # or anonymous file input (Ashby's "autofill from résumé" dropzone, Lever's
        # generic upload) must NOT — over-attaching there breaks the application.
        if re.search(r"resume|résumé|\bcv\b|curriculum|file-upload", hay):
            return "resume_upload", HIGH
        return None

    # Workday lane: strong deterministic signal — check before generic rules.
    if aid:
        for needle, canon in _AUTOMATION_ID:
            if needle in aid:
                return canon, HIGH
    ac = f.autocomplete.lower().strip()
    if ac in _AUTOCOMPLETE:
        return _AUTOCOMPLETE[ac], HIGH
    if typ == "email":
        return "email", HIGH
    if typ == "tel":
        return "phone", HIGH
    # A field whose entire label is just "name" is the applicant's name.
    if f.name.lower() == "name" or f.label.strip().lower() == "name":
        return "full_name", HIGH
    for canon, rx in _RULES:
        if rx.search(hay):
            return canon, KEYWORD
    if tag == "textarea":
        return "free_text", 0.6
    return None


def form_sig(fields: list[FieldDescriptor]) -> str:
    """Order-independent, whitespace-stable hash of the field set, so the cache
    survives trivial DOM churn (reordering, label re-spacing) instead of
    thrashing."""
    norm = sorted(
        "|".join([f.tag, f.type, f.name, f.id, f.autocomplete, " ".join(f.label.lower().split())])
        for f in fields
    )
    return hashlib.sha256("\n".join(norm).encode()).hexdigest()[:16]


class _LLMItem(BaseModel):
    field_ref: int
    canonical: str


class _LLMOut(BaseModel):
    mappings: list[_LLMItem]


def _llm_map(unresolved: list[FieldDescriptor]) -> dict[int, str]:
    """One LLM call for the whole form (never per field). Returns field_ref →
    canonical, coercing anything outside the vocabulary to 'unknown'."""
    if not unresolved:
        return {}
    vocab = ", ".join(sorted(CANONICAL))

    def _line(f: FieldDescriptor) -> str:
        # T19: fold in the structure-only nearby context (heading/legend) when the
        # page gave us one — it disambiguates bare labels ("Country" under a
        # "Work Authorization" heading). Still no values, ever.
        ctx = f" context={f.context!r}" if f.context else ""
        return f"{f.field_ref}: label={f.label!r} name={f.name!r} type={f.type} tag={f.tag}{ctx}"

    lines = "\n".join(_line(f) for f in unresolved)
    messages = [
        {
            "role": "system",
            "content": (
                "You classify job-application form fields into a fixed vocabulary of canonical keys. "
                "You only say what a field ASKS FOR — you never invent an answer. Use 'free_text' for "
                "open-ended questions and 'unknown' when unsure. A field whose tag is 'select' or "
                "'combobox' is a DROPDOWN with a fixed option list — it is never 'free_text'; use the "
                "canonical key it asks for, or 'unknown'. Use 'address' for a street / postal / "
                "ZIP / state / province / country address part — NOT 'location' (which is only a general "
                "city). Reply with JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Canonical keys: {vocab}\n\nFields:\n{lines}\n\n"
                'Return {"mappings":[{"field_ref":<int>,"canonical":"<key>"}]}'
            ),
        },
    ]
    resp = llm.chat(messages, format=_LLMOut.model_json_schema())
    items = resp.get("mappings", []) if isinstance(resp, dict) else []
    by_ref = {f.field_ref: f for f in unresolved}
    out: dict[int, str] = {}
    for m in items:
        ref, canon = m.get("field_ref"), m.get("canonical")
        if ref is None:
            continue
        ref = int(ref)
        canon = canon if canon in CANONICAL else "unknown"
        # A dropdown has a fixed option list, so it is never free text. Left as
        # 'free_text' it routes to the answerer, whose drafted prose then lands in
        # the control verbatim (Greenhouse renders School/Degree as react-select
        # comboboxes). The client guards this too; this keeps the CACHE clean.
        f = by_ref.get(ref)
        if canon == "free_text" and f is not None and f.tag in ("select", "combobox"):
            canon = "unknown"
        out[ref] = canon
    for f in unresolved:  # anything the LLM skipped is unknown, never dropped
        out.setdefault(f.field_ref, "unknown")
    return out


def resolve(host: str, fields: list[FieldDescriptor], session: Session) -> list[FieldMappingOut]:
    sig = form_sig(fields)
    cached = session.scalar(
        select(FieldMapping).where(FieldMapping.host == host, FieldMapping.form_sig == sig)
    )
    if cached:
        return [
            FieldMappingOut(field_ref=int(ref), source="cache", **entry)
            for ref, entry in cached.mapping.items()
        ]

    resolved: dict[int, dict] = {}
    unresolved: list[FieldDescriptor] = []
    for f in fields:
        h = heuristic_map(f)
        if h:
            resolved[f.field_ref] = {"canonical": h[0], "confidence": h[1], "source": "heuristic"}
        else:
            unresolved.append(f)

    for ref, canon in _llm_map(unresolved).items():
        resolved[ref] = {"canonical": canon, "confidence": 0.8 if canon != "unknown" else 0.3, "source": "llm"}

    # Promote the discovery into the cache (store map only; source is per-lookup).
    stored = {str(ref): {"canonical": v["canonical"], "confidence": v["confidence"]} for ref, v in resolved.items()}
    session.add(FieldMapping(host=host, form_sig=sig, mapping=stored))
    session.commit()

    return [FieldMappingOut(field_ref=ref, **entry) for ref, entry in resolved.items()]


def correct(host: str, fields: list[FieldDescriptor], field_ref: int, canonical: str, session: Session) -> None:
    """T19 learning loop: upsert ONE field's mapping into the (host, form_sig)
    cache from a user correction. Stored at HIGH confidence so it wins next run.
    Coerced to the vocabulary. Structure + canonical only — no value ever reaches
    this path. In the real flow a resolve() ran first (during the fill), so the
    row exists and this just overrides one entry; the no-row case seeds it."""
    canon = canonical if canonical in CANONICAL else "unknown"
    sig = form_sig(fields)
    entry = {"canonical": canon, "confidence": HIGH}
    row = session.scalar(
        select(FieldMapping).where(FieldMapping.host == host, FieldMapping.form_sig == sig)
    )
    if row:
        row.mapping = {**row.mapping, str(field_ref): entry}  # reassign so SQLAlchemy sees the change
    else:
        session.add(FieldMapping(host=host, form_sig=sig, mapping={str(field_ref): entry}))
    session.commit()
