"""Deal-breakers in a JD (T39): minimum experience, US citizenship, no visa
sponsorship, security clearance. Regex, not the LLM: instant, free, and every
flag is a sentence quoted verbatim from the posting, so the user can check it.
Every pattern and guard below comes from phrasing in 714 real postings
(four samples, 2026-09-28), plus common "no sponsorship" wording found on the web."""

import re

from app.schemas.jd import JdScreen

QUOTE_MAX = 300

# A sentence ends at . ! ? before a capital - never inside "U.S." or "e.g.":
# real postings broke "only U.S. / citizens are authorized" in two there.
_SENTENCE = re.compile(r"(?<![A-Za-z]\.[A-Za-z]\.)(?<=[.!?])\s+(?=[A-Z0-9\"“(•-])")

# "3+ years", "0-2 years", "Minimum 7.5 year(s)", "Two (2) or more years", "12 yrs."
_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
_N = rf"(\d+(?:\.\d+)?|{'|'.join(_WORDS)})"
_YEARS = re.compile(
    # a ceiling ("up to 2 years") or a window ("in the last three years") is no minimum
    rf"(?:\b(fewer than|up to|within|last)\s+)?"
    rf"(?<![\w.$]){_N}(?:\s*\(\d+\))?\s*\+?\s*(?:(?:-|–|—|to)\s*{_N}(?:\s*\(\d+\))?\s*\+?\s*)?(?:or more\s+)?"
    r"(?:years?|yrs?)\b(?:\(s\))?\.?"
    # an age, a study year or a degree length is not work experience
    r"(?!\s+(?:old|of age|ago|of (?:undergraduate|college|university|school|study|full.time education)))", re.I)
# The number must be about working: "of experience" - or, with no such word, a
# line that leads with its years ("8+ years in z/OS", "- 5+ years building ...").
# Leading is what tells those from "With over 25 years of ... expertise", "10+
# years of runway", "30 days after six years of service", "two years in a row".
_WORK = re.compile(r"experience", re.I)
_YEARS_OF = re.compile(r"(?:years?|yrs?)\b(?:\(s\))?\.?\s+(?:of|in|across|building)\b", re.I)
_LEAD = re.compile(r"(?:[^:]{0,60}:)?[\W_]*")  # an optional "Label:", then bullets
# Degree paths in one sentence, in any order ("Doctorate ... 0 years; Master's
# ... 3 years; Bachelor's ... 5 years" - KLA; "Master's degree ... four years'
# experience ..., or possess a Bachelor's degree with at least ..." - Mimecast):
# the bachelor's path is the bar.
_PATHS = re.compile(r";|,\s*or\b", re.I)
# Only a bachelor's clause with a number: in "Bachelor's degree in ...; 8+ years
# of ..." the ";" separates two requirements, not two paths.
_BACHELOR = re.compile(r"(?i:bachelor)|\bB\.?S\b|\bB\.?A\b")
# A number that stands in for a bachelor's is no minimum: "or 4+ years of ...
# experience in lieu of degree", "certifications may be substituted for a
# Bachelor's degree or 4 years", "No degree and 12+ years", "Associate's degree
# and 10+ years", "or 3+ years of ... experience instead of a degree", "or five
# (5) years of equivalent experience". Only that number and its own clause: "12
# yrs., B.S. or 10 yrs. w/ M.S., 4 yrs. ... may be substituted" still requires 12,
# "degree ... or equivalent experience, with 5+ years of ..." still requires 5.
_SUBSTITUTE = re.compile(
    r"\bin lieu\b|\bsubstitut|\bno degree\b|high school|\bhs diploma\b|\bged\b|\bassociate'?s?\b"
    r"|instead of a degree|equivalent experience", re.I)
_OVERALL = re.compile(r"\s+(?:of\s+)?(?:overall|total)\b", re.I)
_MONTHS = re.compile(r"(\d+)\s*months?\s*(?:-|–|to)\s*$", re.I)
# ponytail: a naive cap. The highest real minimum in 714 postings is 15 years; company
# history ("Drawing on more than 150 years of experience", "30+ years of
# combined AI experience on the founding team") is not a job's bar.
MAX_YEARS = 25

# Preferred, not required: the line says so, or it sits in a preferred section
# ("Preferred Qualifications", "Nice If You Have", "Bonus Points"). Not
# "preferably"/"ideally": "4-7 years of work experience, preferably in inkjet"
# still requires the years. Not "Recommended": both real uses (HP, Citi) head
# the main requirements.
_PREFERRED = re.compile(
    # "a plus", "a strong plus" - not "Bachelor's degree plus 3 years"
    r"\bprefer(?:red|ence)?\b|nice[- ]to[- ]haves?|nice if|\bbonus\b|\ban?\s+(?:\w+\s+)?plus\b|\bdesired\b"
    r"|desirable|advantageous|helpful", re.I)

# An aside is not the line's status: "3 years ... with web application frameworks
# (e.g., Angular (preferred), React ...)" still requires the years.
_ASIDE = re.compile(r"\([^()]*\)")

_US = r"(?:U\.S\.A?\.?|U\.S\b|USA?\b|(?i:united states|american))"
_CITIZEN = re.compile(rf"{_US}\s*(?i:citizens?(?:hip)?|persons?)\b|(?i:\bcitizens?(?:hip)?),?\s+{_US}")
# the EEO line "without regard to ... citizenship status", and E-Verify's
# "U.S. Citizenship and Immigration Services"
_NOT_CITIZEN = re.compile(
    r"regardless of|without regard|discriminat|on the basis of|equal (?:employment )?opportunit|immigration services",
    re.I)

_SPONSOR = re.compile(r"\bsponsor(?:ship|ing)?\b|\bvisas?\b|\bh-?1-?b\b", re.I)
# "n't": job posts quoted as saying "visa sponsorship isn't provided" (Quora)
_NEGATION = re.compile(r"\b(?:not|no|unable|cannot|without|never|nor)\b|n[’']t\b", re.I)
# "without sponsorship for an export license"; a hedge is no explicit "no":
# "Sponsorship for this role is not guaranteed", "we can't always guarantee success"
_NOT_VISA = re.compile(r"export license|guarantee", re.I)

# "Public Trust" as a clearance is capitalized in every real use; "strengthens
# public trust" is marketing copy
_CLEARANCE = re.compile(r"(?i:\bts\s*/+\s*sci\b|\btop secret\b|\bpolygraph\b)|\bPublic Trust\b|\bPUBLIC TRUST\b")
# A bare "clearance" counts only beside a security word: GM's "competitiveness
# in clearances, component locations" and GE's "clearances and fits" are machining.
_CLEARANCE_WORD = re.compile(r"\bclearances?\b", re.I)
_SECURITY = re.compile(
    r"\bsecurity\b|\bsecret\b|\bts\b|\bsci\b|\bdod\b|\bdoe\b|\bgov|\bfederal\b|\bpoly\b|classified|obtain|maintain"
    r"|eligib|interim|\bactive\b|possess|clearances?\s*(?:required|type|level|status|requirements?)|required clearance",
    re.I)
_NOT_CLEARANCE = re.compile(
    # "Minimum Clearance Required to Start: None", "Public Trust/Other Required: None"
    r"(?:clearance|public trust)[^:]{0,40}:\s*(?:none|n/?a|not required|no)\b"
    # "This position does not require a Security Clearance.", "No Clearance"
    r"|\bnot require\w*\b[^.]{0,40}clearance|\bno (?:security )?clearance\b"
    r"|\bfactors\b"  # pay: "Offers are based on factors, such as ... security clearances"
    r"|polygraph protection act"  # the legal notice "Employee Polygraph Protection Act (EPPA)"
    r"|^\W*(?:security )?clearances?(?: information| requirements?| level)?\W*$", re.I)  # a bare heading


def _lines(text: str) -> list[tuple[str, bool]]:
    """(line, in a preferred section). A short "Label:" line is joined to the
    value on the next line ("Clearance:" / "TS/SCI")."""
    out, preferred, label = [], False, ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = len(line.split()) <= 8 and not line.endswith(".")
        titled = line.istitle() or line.isupper()
        if heading and (_PREFERRED.match(line.lstrip("•-* ")) or titled and _PREFERRED.search(line)):
            preferred = True
        elif heading and (line.endswith(":") or titled and len(line.split()) <= 4):
            preferred = False  # the next section: "Additional Information:", PNC's "Work Experience"
        if line.endswith(":") and len(line) <= 60:
            label = line  # only the nearest: consecutive labels would pile up
            continue
        out.append((f"{label} {line}".strip(), preferred))
        label = ""
    if label:
        out.append((label, preferred))
    return out


def _quote(sentence: str) -> str:
    return sentence if len(sentence) <= QUOTE_MAX else sentence[:QUOTE_MAX - 1].rstrip() + "…"


def _min_years(sentence: str) -> float | None:
    """The sentence's minimum years of work experience, or None."""
    if not _WORK.search(sentence):
        first = _YEARS.search(sentence)
        if not (first and first.start() == _LEAD.match(sentence).end() and _YEARS_OF.search(sentence)):
            return None
    part = next((p for p in _PATHS.split(sentence) if _BACHELOR.search(p) and _YEARS.search(p)), sentence)
    found = []  # the first number, then any "overall"/"total" one
    for m in _YEARS.finditer(part):
        before = re.split(r"[,;]", part[:m.start()])[-1]
        after = re.split(r"[,;]", part[m.end():], maxsplit=1)[0]
        if m.group(1) or _SUBSTITUTE.search(before + after) or found and not _OVERALL.match(part, m.end()):
            continue
        n = m.group(2).lower()
        years = float(_WORDS.get(n, n))
        if months := _MONTHS.search(before):  # "around 18 months to 4 years' experience"
            years = round(int(months.group(1)) / 12, 1)
        found.append(years)
    if not found or found[0] > MAX_YEARS:
        return None
    # "3+ years ... with 8+ years of overall experience" requires 8; "3 years ..., of
    # which 2-3 years overall" still requires 3: an overall number only raises the bar
    return max(y for y in found if y <= MAX_YEARS)


def screen(text: str) -> JdScreen:
    experience: dict[str, float] = {}
    citizenship, sponsorship, clearance = [], [], []
    for line, preferred in _lines(text):
        for sentence in _SENTENCE.split(line):
            sentence = sentence.strip()
            quote = _quote(sentence)
            if not preferred and not _PREFERRED.search(_ASIDE.sub("", sentence)) \
                    and (years := _min_years(sentence)) is not None:
                experience.setdefault(quote, years)
            if _CITIZEN.search(sentence) and not _NOT_CITIZEN.search(sentence):
                citizenship.append(quote)
            # the "no" must be in the sponsorship's own clause: "Visa sponsorship
            # available; relocation not available." offers sponsorship
            if any(_SPONSOR.search(c) and _NEGATION.search(c) for c in sentence.split(";")) \
                    and not _NOT_VISA.search(sentence):
                sponsorship.append(quote)
            if (_CLEARANCE.search(sentence) or _CLEARANCE_WORD.search(sentence) and _SECURITY.search(sentence)) \
                    and not _NOT_CLEARANCE.search(sentence):
                clearance.append(quote)
    # Every required line must be met, so the minimum is the highest of them;
    # its sentence goes first.
    ranked = sorted(experience, key=experience.get, reverse=True)
    return JdScreen(
        min_years=experience[ranked[0]] if ranked else None, experience=ranked,
        citizenship=list(dict.fromkeys(citizenship)), no_sponsorship=list(dict.fromkeys(sponsorship)),
        clearance=list(dict.fromkeys(clearance)))
