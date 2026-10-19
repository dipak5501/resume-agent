"""Canonical field vocabulary (T12). The shared contract for what an
application-form field *means*, decoupled from its label. Mirrors the
extension's `Canonical` type in extension/src/shared/types.ts — keep them in
sync. The LLM lane MAPS a label to one of these; it never invents a value."""

CANONICAL = frozenset(
    {
        "full_name",
        "first_name",
        "last_name",
        "email",
        "phone",
        "location",
        "address",
        "linkedin",
        "github",
        "portfolio",
        "website",
        "work_authorization",
        "years_experience",
        "resume_upload",
        "cover_letter",
        "free_text",
        "unknown",
    }
)

# --- Answer-bank vocabulary (T13) -------------------------------------------
# What a *screening question* asks (vs CANONICAL above, which is what a form
# *field* asks). The resolver classifies a question to one of these keys; the
# value maps to a mode: verbatim keys fill from the bank as-is (no LLM),
# adaptable keys let the LLM tailor the stored template to this JD.
ANSWER_CANONICAL: dict[str, str] = {
    "salary_expectation": "verbatim",
    "work_authorization": "verbatim",
    "requires_sponsorship": "verbatim",
    "notice_period": "verbatim",
    "willing_to_relocate": "verbatim",
    "preferred_location_remote": "verbatim",
    "earliest_start_date": "verbatim",
    "years_experience": "verbatim",
    "how_heard_about_us": "verbatim",
    "why_leaving": "adaptable",
    "why_company": "adaptable",
    "tell_me_about_yourself": "adaptable",
}

# Hard trust boundary: questions the classifier tags with one of these are NEVER
# LLM-answered. Filled only from an explicit stored answer, else left blank +
# flagged high-stakes. They are classify-only targets, never seeded bank rows.
NEVER_AUTO = frozenset({"eeo_demographic", "criminal_background"})

# The full label set the LLM question-classifier may return ("none" = no match →
# fresh draft). Kept here so the resolver and its prompt share one source.
ANSWER_CLASSIFY = frozenset(ANSWER_CANONICAL) | NEVER_AUTO | {"none"}
