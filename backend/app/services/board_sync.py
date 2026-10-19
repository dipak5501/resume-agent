import asyncio
import errno
import functools
import hashlib
import html
import json
import math
import os
import random
import sys
import time
import traceback
import re
import unicodedata
from datetime import datetime, timezone, timedelta

import httpx
from urllib.parse import unquote, urlparse
from urllib.robotparser import RobotFileParser
from email.utils import parsedate_to_datetime
from sqlalchemy import case, literal, select, func, delete, or_, update
from sqlalchemy.dialects.sqlite import insert

# Import the module, not the name: tests rebind db.SessionLocal to a temp
# database, and `from app.db import SessionLocal` would capture the real one.
from app import db as _db
from app.core import config  # module, not names: tests rebind config.DATA_DIR
from app.models import TrackedCompany, JobPosting
from app.services import board_policy, jd_adapters

# Identify honestly. These are public, unauthenticated board APIs and the project's
# stated ethic is assisted-never-autonomous, so pretending to be Chrome is both
# unnecessary and off-brand. Mirrors jd_fetch._UA.
USER_AGENT = "Mozilla/5.0 (compatible; resume-agent/1.0; +job-board)"


def _pipe_gone(exc: BaseException) -> bool:
    return isinstance(exc, BrokenPipeError) or getattr(exc, "errno", None) in (errno.EPIPE, errno.EIO)


class _PipeSafe:
    """stdout/stderr after the terminal reader has exited.

    print() raises BrokenPipeError on that stream. On 2026-10-17 the harvest
    loops caught it, traceback.print_exc() raised the same error, and every
    checker exited. The API kept serving the last board it had.
    """

    def __init__(self, stream):
        self._stream = stream

    def write(self, data):
        try:
            return self._stream.write(data)
        except OSError as exc:
            if _pipe_gone(exc):
                return 0
            raise

    def flush(self):
        try:
            self._stream.flush()
        except OSError as exc:
            if _pipe_gone(exc):
                return None
            raise

    def __getattr__(self, name):
        return getattr(self._stream, name)


def guard_stdio() -> None:
    """Harvest logs must not end the harvest when the terminal is gone."""
    if not isinstance(sys.stdout, _PipeSafe):
        sys.stdout = _PipeSafe(sys.stdout)
    if not isinstance(sys.stderr, _PipeSafe):
        sys.stderr = _PipeSafe(sys.stderr)


def _log_exc() -> None:
    try:
        traceback.print_exc()
    except OSError as exc:
        if not _pipe_gone(exc):
            raise

BOARD_TIMEOUT = 10.0          # unchanged: worst real board (lever/palantir, 6MB) takes ~1.8s
BOARD_MAX_BYTES = 64 * 1024 * 1024   # largest real board is Ashby/bjakcareer at 33.6MB (2026-09-23)

# Slugs come from untrusted sources (SimplifyJobs listings, Serper results,
# pasted links) and are interpolated into a vendor URL path. The host is always a
# literal, so this is not an SSRF vector, but a traversal-shaped slug has no
# business being fetched. Single inner spaces: 92 live Ashby boards are named
# like "flock safety" (T44); httpx sends the space as %20.
_SLUG_OK = re.compile(r"(?!.*\.\.)[A-Za-z0-9_.-]+(?: [A-Za-z0-9_.-]+)*")  # fullmatch; no ".." anywhere

# T31 adaptive revisit (Nutch AdaptiveFetchSchedule style): each board's interval
# shrinks when a NEW job for our roles appears and grows x1.2 when nothing new,
# within a floor and a ceiling set by whether it lists our roles at all.
HARVEST_INTERVAL = timedelta(hours=1)   # a board's starting interval, before we know it
MIN_INTERVAL = timedelta(seconds=60)    # floor: a board that lists our roles
ACTIVE_CEILING = timedelta(seconds=60)  # lists our roles: rechecked about every minute
QUIET_INTERVAL = timedelta(hours=24)    # lists none of our roles: watched, cheaply
# T30: 91% of weekday postings (715 of 783) land 13:00-01:00 UTC. Overnight,
# intervals don't grow. The floor matches the minute cadence so a hiring board
# is not pushed back to hourly while the Job Board is open.
NIGHT_FLOOR = MIN_INTERVAL
# After this many priority checks, take one quiet or never-checked board.
# Those imports are thousands of boards; they rotate, and they do not go every minute.
WIDE_EVERY = 4
PARK_FOR = timedelta(days=7)    # a board on no ATS we list is rechecked weekly
WORKER_IDLE = 30.0              # seconds a vendor worker sleeps when nothing is due
HEALTH_EVERY = 600.0            # seconds between a worker's health lines
SCOUT_INTERVAL = timedelta(hours=24)   # Serper: 7 credits a run
# T45: Simplify is a free GitHub file that changes ~30 times a day; 3 of 7 untracked
# companies in the 2026-10-06 audit were listed after the daily run.
SIMPLIFY_INTERVAL = timedelta(hours=2)
RETENTION_INTERVAL = 15 * 60    # independent of the potentially long harvest cycle
JITTER = (1.0, 3.0)             # polite gap between requests to ONE vendor
MAX_BACKOFF = 300.0              # cap on an honoured Retry-After
MAX_SLOWDOWN = 10.0              # a strained vendor's gap grows to at most 10x (30s)

SEED_COMPANIES = {  # vendors verified live 2026-09-23 (figma is Greenhouse, plaid moved to Ashby)
    "ashby": ["vercel", "notion", "ramp", "plaid", "linear"],
    "greenhouse": ["airbnb", "stripe", "figma", "discord", "anthropic"]
}


def _wd(host: str, *sites: str) -> list[str]:
    return [f"https://{host}.myworkdayjobs.com/{site}" for site in sites]


# T36: the 2026 Fortune 500 tech companies that post on none of the vendors
# above, every board answered live on 2026-09-24. (provider, slug, name, boards)
# A slug is the company's own domain name where the vendor's id is cryptic
# (amat, bah, spgi, cnx), so its logo resolves; boards, not slugs, identify a
# board, so rediscovery under the vendor's id still dedupes. Upserted each start.
F500_BOARDS = [
    ("workday", "nvidia", "NVIDIA", _wd("nvidia.wd5", "NVIDIAExternalCareerSite")),
    ("workday", "broadcom", "Broadcom", _wd("broadcom.wd1", "External_Career")),
    ("workday", "cisco", "Cisco", _wd("cisco.wd5", "Cisco_Careers")),
    ("workday", "hp", "HP", _wd("hp.wd5", "ExternalCareerSite")),
    ("workday", "intel", "Intel", _wd("intel.wd1", "External")),
    ("workday", "thermofisher", "Thermo Fisher Scientific", _wd("thermofisher.wd5", "ThermoFisherCareers")),
    ("workday", "salesforce", "Salesforce",
     _wd("salesforce.wd12", "External_Career_Site", "Futureforce_NewGradRoles")),
    ("workday", "visa", "Visa", _wd("visa.wd5", "Visa")),
    ("workday", "micron", "Micron Technology", _wd("micron.wd1", "External")),
    ("workday", "hpe", "Hewlett Packard Enterprise", _wd("hpe.wd5", "Jobsathpe", "acjobsite")),
    ("workday", "mastercard", "Mastercard", _wd("mastercard.wd1", "CorporateCareers", "Campus")),
    ("workday", "jabil", "Jabil", _wd("jabil.wd5", "Jabil_Careers")),
    ("workday", "appliedmaterials", "Applied Materials", _wd("amat.wd1", "External")),
    ("workday", "adobe", "Adobe", _wd("adobe.wd5", "external_experienced")),
    ("workday", "fiserv", "Fiserv", _wd("fiserv.wd5", "EXT")),
    ("workday", "leidos", "Leidos", _wd("leidos.wd5", "External")),
    ("workday", "spglobal", "S&P Global", _wd("spgi.wd5", "SPGI_Careers")),
    ("workday", "kyndryl", "Kyndryl", _wd("kyndryl.wd5", "KyndrylProfessionalCareers", "KyndrylEarlyCareers")),
    ("workday", "expedia", "Expedia Group", _wd("expedia.wd108", "search")),
    ("workday", "kla", "KLA", _wd("kla.wd1", "Search", "UR")),
    ("workday", "boozallen", "Booz Allen Hamilton", _wd("bah.wd1", "BAH_Jobs")),
    ("workday", "motorolasolutions", "Motorola Solutions", _wd("motorolasolutions.wd5", "Careers")),
    ("workday", "ebay", "eBay", _wd("ebay.wd5", "apply")),
    # "analog" is a live Ashby board; analogdevices.com does not answer, so the tenant id stays
    ("workday", "analogdevices", "Analog Devices", _wd("analogdevices.wd1", "External")),
    ("workday", "fisglobal", "FIS", _wd("fis.wd5", "SearchJobs")),
    ("workday", "globalpayments", "Global Payments", _wd("tsys.wd1", "TSYS")),  # its own tenant 422s
    ("workday", "workday", "Workday", _wd("workday.wd5", "Workday_Jobs")),
    ("workday", "qvc", "QVC Group", _wd("qvc.wd5", "QRG")),
    ("workday", "paloaltonetworks", "Palo Alto Networks", _wd("paloaltonetworks.wd5", "panwexternalcareers")),
    ("workday", "caci", "CACI", _wd("caci.wd1", "External")),
    ("workday", "marvell", "Marvell Technology", _wd("marvell.wd1", "MarvellCareers")),
    ("workday", "kbr", "KBR", _wd("kbr.wd5", "KBR_Careers")),
    ("workday", "dxc", "DXC Technology", _wd("dxctechnology.wd1", "DXCJobs")),
    ("workday", "concentrix", "Concentrix", _wd("cnx.wd1", "external_global")),
    ("workday", "chewy", "Chewy", _wd("chewy.wd5", "External")),
    ("oracle", "oracle", "Oracle", ["https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001"]),
    ("oracle", "dell", "Dell Technologies",  # its Workday tenant 422s
     ["https://iawmqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/careers"]),
    ("oracle", "ti", "Texas Instruments",
     ["https://edbz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX"]),
    ("eightfold", "microsoft", "Microsoft", ["https://apply.careers.microsoft.com/careers?domain=microsoft.com"]),
    ("eightfold", "qualcomm", "Qualcomm", ["https://qualcomm.eightfold.ai/careers?domain=qualcomm.com"]),
    ("eightfold", "paypal", "PayPal", ["https://paypal.eightfold.ai/careers?domain=paypal.com"]),
    ("eightfold", "lamresearch", "Lam Research", ["https://lamresearch.eightfold.ai/careers?domain=lamresearch.com"]),
    ("smartrecruiters", "servicenow", "ServiceNow", None),
    ("smartrecruiters", "westerndigital", "Western Digital", None),
    ("smartrecruiters", "aristanetworks", "Arista Networks", None),
    ("amazon", "amazon", "Amazon", None),
    ("apple", "apple", "Apple", None),
]

# A title names the ROLE first and the TEAM second: "Software Engineer, Sales
# Platform" is a SWE role, "Account Executive, AI Sales" is not. So the role and
# discipline gates read the ROLE SEGMENT, while seniority and unwanted domains
# are checked against the WHOLE title ("Software Engineer, iOS" is a mobile role
# even though its head is generic; "Engineer, Senior or Staff" is senior).
_HEAD = re.compile(r"[,–—(]| - ")

# Gate 1: the role segment must actually name an engineering role. "software"
# alone is not a role ("Software Asset Coordinator"), but "Flight Software
# Intern" is one.
_ENG_ROLE = re.compile(
    r"\b(software engineer|engineer|engineering|engr|developer|programmer|swe|sde"
    r"|member of technical staff|software (intern(ship)?|associate|co-?op))\b", re.I)

# Some heads name no role at all: an early-career marker ("Intern, Software
# Engineering, 2027") or a program prefix before a dash ("Accelerator Program -
# Software Engineer"). Then the role is the next segment - unless the head is a
# person's job ("Technical Recruiter - Software Engineering").
_MARKER_HEAD = re.compile(r"\s*(intern(ship)?|co-?op|new grad(uate)?|contract(or)?|university)\s*", re.I)
_PEOPLE_ROLE = re.compile(
    r"\b(recruit\w*|sourc\w*|coordinator|designer|technician|counsel|accountant"
    r"|representative|consultant|officer|administrator)\b", re.I)

# Gate 2: above the target band (new grad through mid). "staff" is excluded
# EXCEPT after "technical", so "Staff Machine Learning Engineer" is rejected
# while "Member of Technical Staff" survives.
_TOO_SENIOR = re.compile(
    r"\b(senior|sr\.?|snr\.?|principal|distinguished|lead|manager|director|vp|head of"
    r"|architect|chief)\b|(?<!technical )\bstaff\b", re.I)

# Gate 3: engineering, but not software. Help desk and the other CS titles are
# accepted earlier (_help_desk_or_cs). This list still drops product support,
# customer engineering, and the hardware-adjacent "IT"/"network" titles that
# never name help desk, service desk, or a CS role.
# NB: no "recruit" here. Gate 1 already rejects "AI Recruiter"/"Technical
# Recruiter" (no engineering noun), and a prefix match would wrongly reject
# "Recruiting Analytics Data Engineer", which IS a data-engineering role.
_NOT_SOFTWARE = re.compile(
    r"\b(electrical|mechanical|civil|chemical|industrial|hardware|optical|thermal"
    r"|manufacturing|silicon|data ?cent(er|re)\w*|facilit\w*|audio|video|\bav\b"
    r"|sales|presales|pre-sales|marketing|account executive|customer"
    r"|solutions?|support|\bit\b|partner|field|salesforce|sfdc|developer relations|devrel"
    r"|documentation|technical writer|network"
    r"|copywriter|scientist|analyst|specialist)\b", re.I)

# Gate 4: software, but a domain we do not want (QA/test and mobile). Deliberately
# targeted: a bare "quality" or "test" would reject "Software Engineer, Search
# Quality", which is relevance work, not QA.
_UNWANTED_DOMAIN = re.compile(
    r"\b(qa|sdet|ios|android|mobile)\b|quality assurance"
    r"|\b(engineer|engineering) in test\b|\btest(ing)? engineer\b|\bsoftware test(ing)?\b", re.I)

# Gate 5: positive identification of SOFTWARE work, like the location filter
# below. Gate 3 was a denylist, and on aerospace/defense boards a bare
# "engineer" let Propulsion, Avionics, Wiring Harness and PCB Layout roles
# through (T29 audit: 144 of 450 kept titles). A role noun that says software
# passes outright; a software field passes unless it names hardware; a bare
# "engineer" needs software evidence somewhere and no hardware anywhere.
_SOFTWARE_ROLE = re.compile(r"\b(software|developer|swe|sde|member of technical staff)\b", re.I)
_SOFTWARE_FIELD = re.compile(
    r"\b(programmer|back.?end|front.?end|full.?stack|web|data|analytics|ml|machine learning"
    r"|ai|llm|agent\w*|infra\w*|platform|devops|site reliability|sre|cloud|security|devsecops"
    r"|forward deployed|founding|research|applied|distributed|kernel|operating systems"
    r"|compiler|database|firmware|embedded|hpc|perception|robotics software|simulation"
    r"|growth|red team|threat|vulnerability|grc|abuse|detection"
    r"|incident response|identity|iam|build|performance|integration|design engineer)\b", re.I)
# Weaker hints, trusted only when no hardware word appears in the whole title.
# "systems" stays ambiguous-but-kept: Cloudflare's SWEs are "Systems Engineers".
_SOFTWARE_HINT = re.compile(
    r"\b(product|reliability|robotics|autonomy|motion planning|tools|api|systems"
    r"|new grad|intern|internship|co-op)\b", re.I)
_HARDWARE = re.compile(
    r"\b(propulsion|avionics|structur\w*|mechanic\w*|mechanism\w*|fluids?|materials?|metals?"
    r"|environmental|pcb|harness|wiring|ewis|rf|battery|powerpack|welding|hvac|construction"
    r"|ordnance|warhead|cmm|edm|supplier|supply chain|sourcing|npi|equipment|machine maintenance"
    r"|physical design|design verification|fpga|asic|dfx|dynamics|thermal|power generation"
    r"|bess|solar|launch|recovery|test stand|vacuum|cryogenic|scada|controls?|automation"
    r"|failure analysis|product quality|quality systems|liaison|material flow|technician"
    r"|body|chassis|manufacturing|electronics|hardware"
    # T36: chip and defense boards (Workday). Each word's only effect on the 1,475
    # open titles of 2026-09-24 was to drop one of 27 non-software roles.
    r"|analog|mixed.?signal|ic|gan|radar|hypersonics?|missiles?|launchers?|munitions|weapons?"
    r"|space suit|power delivery|process integration|install|layout|satcom|naval)\b", re.I)


# T40: "(Jr) Machine Learning (ML) Developer": a parenthesis the phrase runs on
# past is an aside; one that ends a phrase still splits it. " – " is " - " typed
# as an en dash.
_PARENS = re.compile(r"\([^)]*\)(?=\s*[\w/])")
_SPACED_DASH = re.compile(r"\s[–—]\s")

# Help desk and the rest of the CS band, in addition to the software titles the
# gates above already keep. The profile's target role stays whatever was saved;
# harvest classification is what broadens. Seniority, QA/mobile, hardware, and
# sales/recruiting still apply, so "Business Help Desk Intern" is stored and the
# feed hides it until Include internships is on.
_HELP_DESK = re.compile(
    r"\b(help[\s-]?desk|service[\s-]?desk|desktop[\s-]support"
    r"|(?:i\.?t\.?|information[\s-]technology)[\s-]support)\b", re.I)
_CS_ROLE = re.compile(
    r"\b(data[\s-](?:analyst|scientist|science)"
    r"|business[\s-]intelligence|\bbi[\s-]analyst\b"
    r"|cyber[\s-]?security|information[\s-]security|security[\s-]analyst|soc[\s-]analyst"
    r"|network(?:ing)?[\s-](?:engineer(?:ing)?|administrator|admin|analyst)"
    r"|systems?[\s-](?:administrator|analyst)|system[\s-]admin|sysadmin"
    r"|(?:i\.?t\.?|information[\s-]technology)[\s-]"
    r"(?:analyst|specialist|administrator|admin|engineer)"
    r"|computer[\s-]science|computer[\s-]scientist)\b", re.I)
# Whole title, and only for this broader band: a software role on a sales team
# ("Software Engineer, Sales Platform") still passes the gates below.
_NOT_DESK = re.compile(
    r"\b(recruit\w*|sourc\w*|sales|marketing|account executive|presales|pre-sales"
    r"|physical security|security guard"
    r"|professor|faculty|lecturer|instructor|teacher|tutor"
    r"|partner|field)\b", re.I)


def _help_desk_or_cs(title: str) -> bool:
    if not (_HELP_DESK.search(title) or _CS_ROLE.search(title)):
        return False
    return not _HARDWARE.search(title) and not _NOT_DESK.search(title)


def _role_segment(title: str) -> str:
    title = _SPACED_DASH.sub(" - ", _PARENS.sub(" ", title))
    sep = _HEAD.search(title)
    if not sep:
        return title
    head = title[:sep.start()]
    if _ENG_ROLE.search(head):
        return head
    following = _HEAD.split(title[sep.end():], 1)[0]
    if _ENG_ROLE.search(following) and (
            _MARKER_HEAD.fullmatch(head)
            or (sep.group() == " - " and not _PEOPLE_ROLE.search(head)
                and not _NOT_SOFTWARE.search(head))):
        return following
    return head


def is_target_role(title: str) -> bool:
    """Software engineering plus help desk and other CS roles, new grad to mid.

    Software titles still go through the gates. Help desk (help desk, service
    desk, IT support, desktop support) and other CS work (data, systems, IT,
    cybersecurity, networking, computer science) are accepted beside them.
    The saved profile target role is not rewritten.
    """
    if _TOO_SENIOR.search(title) or _UNWANTED_DOMAIN.search(title):
        return False
    if _help_desk_or_cs(title):
        return True
    role = _role_segment(title)
    if not _ENG_ROLE.search(role) or _NOT_SOFTWARE.search(role):
        return False
    if _SOFTWARE_ROLE.search(role):
        return True
    if _SOFTWARE_FIELD.search(role) and not _HARDWARE.search(role):
        return True
    # A bare head ("Engineer, Desktop Software") leaves the rest of the title to name the work.
    return bool(_SOFTWARE_FIELD.search(title) or _SOFTWARE_HINT.search(title)
                or (_SOFTWARE_ROLE.search(title) and not _NOT_SOFTWARE.search(title))) \
        and not _HARDWARE.search(title)


# Harvest still keeps internships (a Board control can ask for them). The feed
# hides them unless asked: there is no level on the profile, and full-time is
# the default. "Internal" and "cooperative" are not internships.
_INTERN_WORD = re.compile(
    r"(?<![A-Za-z])(?:intern(?:ship)?s?|co-?ops?)(?![A-Za-z])", re.I)


def is_internship(title: str) -> bool:
    return bool(_INTERN_WORD.search(title or ""))


# Punctuation becomes a space so "Co-Op" and "Intern," tokenize the same way
# is_internship does, while "internal" stays one word.
_TITLE_SEPARATORS = "-–—/()[]{}.,:;!?&+|•'\""
_INTERN_TOKENS = (" intern ", " interns ", " internship ", " internships ",
                  " co op ", " co ops ", " coop ", " coops ")


def internship_clause(column=JobPosting.title):
    text = func.lower(column)
    for ch in _TITLE_SEPARATORS:
        text = func.replace(text, ch, " ")
    padded = literal(" ").concat(text).concat(literal(" "))
    return or_(*(padded.like(f"%{token}%") for token in _INTERN_TOKENS))


# US + Canada, any state or city. Positive identification, not a denylist: the
# old EXCLUDE_LOCATIONS blocked ~25 named places and let everything else through,
# so Israel/Switzerland/Korea/Ukraine all passed by omission.

# Splits a multi-location posting into units. NOT on comma, which separates
# "city, state" inside a single unit.
_LOC_UNITS = re.compile(r"[|;•\n]|\s+or\s+|\s/\s")

# Unambiguous US/Canada evidence: country words, full state/province names, and
# city names that appear with no state or country attached.
_DOMESTIC = re.compile(
    r"\b(united states|u\.s\.a?|usa|canada|north america|amer|usca"
    r"|alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware"
    r"|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana"
    r"|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska"
    r"|nevada|new hampshire|new jersey|new mexico|new york|north carolina"
    r"|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina"
    r"|south dakota|tennessee|texas"
    r"|utah|vermont|virginia|washington|wisconsin|wyoming"
    r"|ontario|british columbia|quebec|alberta|manitoba|saskatchewan|nova scotia"
    r"|new brunswick|newfoundland|labrador|prince edward island|yukon|nunavut"
    r"|northwest territories"
    r"|san francisco|new york city|nyc|seattle|austin|boston|chicago|denver|atlanta"
    r"|miami|portland|los angeles|san diego|san jose|palo alto|mountain view|dallas"
    r"|houston|philadelphia|phoenix|detroit|pittsburgh|san mateo|sunnyvale|redmond"
    r"|bellevue|toronto|vancouver|montreal|ottawa|calgary|waterloo)\b", re.I)
# Uppercase only, and only abbreviations confirmed present in real board data.
# "LA" is deliberately absent: both real occurrences are "Remote - LA" meaning
# Louisiana (alongside "Remote - OK"/"Remote - TX"), which the code rule covers.
# "US" ("US Remote", "Remote - US") must count once regions are foreign, or
# "Remote - US or Europe" would read as unknown + foreign and be dropped.
_DOMESTIC_ABBR = re.compile(r"\b(SF|NYC|DC|CHI|SEA|US)\b")

# Two-letter state/province codes. Checked only AFTER the foreign list, because
# many collide with ISO country codes: NL is Newfoundland *and* the Netherlands,
# DE Delaware and Germany, IL Illinois and Israel, IN Indiana and India.
_DOMESTIC_CODE = re.compile(
    r"[,\-]\s*(A[LKZR]|C[AOT]|DE|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]"
    r"|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY]|DC"
    r"|ON|BC|QC|AB|MB|SK|NS|NB|NL|PE|YT|NT|NU)\b")

_FOREIGN = re.compile(
    r"\b(united kingdom|\buk\b|england|scotland|wales|ireland|dublin|london"
    r"|manchester|edinburgh|belfast|luxembourg|iceland|reykjavik"
    r"|india|bengaluru|bangalore|mumbai|delhi|hyderabad|pune|chennai|gurugram|noida"
    r"|germany|berlin|munich|munchen|hamburg|frankfurt|koln|cologne|dusseldorf"
    r"|france|paris|lyon|spain|madrid|sevilla|seville"
    r"|barcelona|portugal|lisbon|lisboa|porto|italy|milan|milano|rome|roma|torino"
    r"|firenze|netherlands|amsterdam|den haag|the hague"
    r"|belgium|brussels|switzerland|zurich|geneva|geneve|basel|austria|vienna|wien"
    r"|poland|warsaw|warszawa"
    r"|krakow|czech|prague|praha|slovakia|bratislava|romania|bucharest|bucuresti"
    r"|bulgaria|sofia"
    r"|hungary|budapest|greece|athens|serbia|belgrade|croatia|zagreb|malta|valletta"
    r"|sweden|stockholm|malmo|goteborg|gothenburg|norway|oslo|denmark|copenhagen"
    r"|kobenhavn|aarhus|finland|helsinki"
    r"|estonia|latvia|lithuania|ukraine|kyiv|russia|moscow|israel|tel aviv"
    r"|turkey|istanbul|\buae\b|dubai|abu dhabi|saudi|riyadh|jeddah|qatar|doha"
    r"|singapore|japan|tokyo|osaka|china|beijing|shanghai|shenzhen|hong kong"
    r"|taiwan|taipei|korea|seoul|philippines|manila|indonesia|jakarta|vietnam"
    r"|hanoi|ho chi minh|thailand|bangkok|malaysia|kuala lumpur|australia|sydney"
    r"|melbourne|brisbane|perth|new zealand|auckland|wellington|south africa"
    r"|cape town|johannesburg|nigeria|lagos|kenya|nairobi|egypt|cairo|morocco"
    r"|casablanca|brazil|sao paulo|rio de janeiro|mexico|cdmx|guadalajara"
    r"|argentina|buenos aires|colombia|bogota|chile|santiago|peru|lima"
    r"|costa rica|panama|uruguay|montevideo|laos|vientiane|emea|apac|latam|anz"
    r"|europe|asia|middle east|africa|slovenia|ljubljana)\b", re.I)


# Two-letter country codes that are NOT also a US state or Canadian province, so
# they can be read as foreign with no ambiguity. DE, NL, IL, IN, CO, AR, ID, PA,
# SK, MA, MT, LA, PE and GA are all deliberately absent - each is a US state or
# province code too, and the collision is what this module already guards against.
_FOREIGN_CODE = re.compile(
    r"[,\-]\s*(CH|SE|NO|DK|FI|IE|MX|BR|JP|CN|SG|AU|NZ|ZA|AE|PT|ES|FR|IT|GR|TR"
    r"|KR|TW|PH|TH|VN|MY|PL|CZ|RO|HU|BG|HR|RS|UA|RU|EG|KE|NG|CL|GB|AT|BE|LU|IS"
    r"|EE|LV|LT|SI|HK|SA|QA|KW|CR|UY|EC)\b")


# NFKD decomposes accents (Zurich, Krakow, Sao Paulo) but NOT letters that are
# distinct characters rather than base+mark: Kobenhavn, Malmo, Lodz, Duesseldorf.
# Case is preserved on purpose: _DOMESTIC_CODE and _FOREIGN_CODE match UPPERCASE
# two-letter codes, so lowercasing here would silently stop "Raleigh, NC" from
# counting as domestic and break any-valid-wins.
_TRANSLIT = str.maketrans({
    "\u00f8": "o", "\u00d8": "O", "\u00e6": "ae", "\u00c6": "AE", "\u00e5": "a", "\u00c5": "A",
    "\u00df": "ss", "\u0142": "l", "\u0141": "L", "\u0111": "d", "\u0110": "D",
    "\u0131": "i", "\u00fe": "th", "\u00de": "TH", "\u00f0": "d", "\u00d0": "D",
})


def _translit(text: str) -> str:
    return text.translate(_TRANSLIT)


def _classify_unit(unit: str) -> str:
    """Order matters: a foreign city outranks a two-letter code that merely looks
    like a US state. "Amsterdam, NL" is the Netherlands, not Newfoundland."""
    if _DOMESTIC.search(unit) or _DOMESTIC_ABBR.search(unit):
        return "domestic"
    if _FOREIGN.search(unit) or _FOREIGN_CODE.search(unit):
        return "foreign"
    if _DOMESTIC_CODE.search(unit):
        return "domestic"
    return "unknown"


def _location_units(location: str) -> list[str]:
    # Strip accents first: "Zurich" is in the foreign list but "Zürich" is what
    # Greenhouse actually sends, and the two never matched. Same for Munchen,
    # Krakow, Sao Paulo, Bogota, Malmo. It also lets "Montreal" match directly
    # instead of relying on the word "Canada" happening to be present.
    folded = "".join(c for c in unicodedata.normalize("NFKD", _translit(location))
                     if not unicodedata.combining(c))
    return [u for u in _LOC_UNITS.split(folded) if u.strip()]


def location_kinds(location: str) -> set[str]:
    return {_classify_unit(u) for u in _location_units(location)}


def is_target_location(location: str | None, country: str | None = None) -> bool:
    """US + Canada, any state or city. Any-valid-wins on multi-location postings.

    "New York, NY | London, UK" is a US job also offered in London, so it is KEPT;
    the old denylist dropped it because London appeared anywhere in the string.
    Unrecognised text is KEPT: silently deleting a real job is worse than showing
    one the user can skip past - unless the vendor states the primary location's
    `country` (ISO alpha-2, T36), which settles it: "TUN - ARIANA" is Tunisia.
    """
    if country in ("US", "CA"):
        return True
    units = _location_units(location) if location else []
    if country is not None:
        # The stated country is the first unit's (both vendors list the primary
        # first), so only the others can still be domestic: "Tunis, TN" is not
        # Tennessee when the vendor says TN, Tunisia.
        return any(_classify_unit(u) == "domestic" for u in units[1:])
    kinds = {_classify_unit(u) for u in units}
    return "domestic" in kinds or "foreign" not in kinds


# Missing/invalid dates must never become now(). The stable sentinel makes them
# ineligible under the publication-age policy instead of falsely fresh.
UNDATED = datetime(1970, 1, 1)


def parse_ats_date(date_str: str | None) -> datetime:
    return jd_adapters.parse_ats_date(date_str) or UNDATED


def seed_db_if_empty(db):
    if not db.execute(select(TrackedCompany.slug).limit(1)).scalar():
        for provider, slugs in SEED_COMPANIES.items():
            for slug in slugs:
                stmt = insert(TrackedCompany).values(
                    slug=slug, provider=provider, discovery_source="seed"
                ).on_conflict_do_nothing()
                db.execute(stmt)
        db.commit()


class RateLimited(Exception):
    """A vendor asked us to slow down. Raised out of the per-company call so the
    harvester backs off ONCE at the loop level, instead of a fixed sleep inside
    sync_company_jobs stalling every remaining company behind it."""

    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after:.0f}s")
        self.retry_after = retry_after


def _retry_after_seconds(resp: httpx.Response, default: float = 300.0) -> float:
    """RFC 9110 allows either a delay in seconds or an HTTP date."""
    raw = (resp.headers.get("retry-after") or "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return default


# Conditional GET (T29). Measured 2026-09-23: after an hour, 643 of 668 live
# boards answered 304, so most passes download almost nothing. In memory on
# purpose: a restart (every code change under --reload) refetches every board
# once, so a filter change always re-applies to all of them. An ETag is only
# trusted once its board's rows are committed (_commit_etag); until then it
# waits in _UNCOMMITTED_ETAGS, so a crash mid-sync can never pin stale rows.
NOT_MODIFIED = object()
_ETAGS: dict[tuple[str, str], str] = {}
_UNCOMMITTED_ETAGS: dict[tuple[str, str], str | None] = {}


def _commit_etag(provider: str, slug: str) -> None:
    etag = _UNCOMMITTED_ETAGS.pop((provider, slug), None)
    if etag:
        _ETAGS[(provider, slug)] = etag
    else:
        _ETAGS.pop((provider, slug), None)


async def _get_board(provider: str, slug: str, client=None) -> list | dict | object | None:
    """The single network path for every board. Returns parsed JSON, None when
    the board is gone (404), or NOT_MODIFIED (304). Raises RateLimited on 429/403
    and HTTPStatusError on anything else, so the caller can tell "this vendor is
    unhappy" from "our code is broken". Endpoint URLs come from jd_adapters so
    they live in one module.
    """
    if not _SLUG_OK.fullmatch(slug):
        raise ValueError(f"refusing suspicious board slug: {slug!r}")
    try:
        adapter = jd_adapters.by_name(provider)
        url = adapter.list_url(slug)
    except (LookupError, AttributeError) as e:  # unknown ATS, or one with no board endpoint
        raise ValueError(f"cannot list a board for provider {provider!r}") from e
    if client is None:  # a lane passes its own, reused connection (T30)
        async with httpx.AsyncClient(timeout=BOARD_TIMEOUT) as own:
            return await _get_board(provider, slug, own)
    body = await _download(client, url, etag_key=(provider, slug))
    return body if body is None or body is NOT_MODIFIED else json.loads(body)


async def _download(client, url: str, *, etag_key=None, body: dict | None = None,
                    gone: tuple[int, ...] = (404,)) -> bytes | object | None:
    """One vendor request: the body, None when the board is gone, or NOT_MODIFIED.
    A JSON `body` makes it a POST (Workday). Raises RateLimited on 429/403 and
    HTTPStatusError on anything else."""
    headers = {"User-Agent": USER_AGENT}
    if etag_key in _ETAGS:
        headers["If-None-Match"] = _ETAGS[etag_key]
    post = {"json": body} if body is not None else {}
    async with client.stream("POST" if post else "GET", url, headers=headers, **post) as resp:
        if resp.status_code == 403 and 403 in gone:
            # Workday answers a private or closed site with its own JSON error
            # (S22 "permission denied", verified); a CDN challenge is HTML.
            head = await anext(resp.aiter_bytes(), b"")  # only the start: an error body has no size cap
            if head.lstrip().startswith(b"{"):
                return None
            raise RateLimited(_retry_after_seconds(resp))
        if resp.status_code in gone:
            return None
        if resp.status_code == 304:  # before raise_for_status: httpx raises on 3xx
            return NOT_MODIFIED
        if resp.status_code in (403, 429):
            raise RateLimited(_retry_after_seconds(resp))
        resp.raise_for_status()
        total, chunks = 0, []
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > BOARD_MAX_BYTES:
                raise ValueError(f"{url}: board exceeds {BOARD_MAX_BYTES} bytes")
            chunks.append(chunk)
        if etag_key is not None:
            _UNCOMMITTED_ETAGS[etag_key] = resp.headers.get("etag")
    return b"".join(chunks)


async def fetch_ashby(slug: str, client=None) -> list[dict] | object | None:
    """None means the board could not be observed (404); [] means it is empty;
    NOT_MODIFIED means it is unchanged since the last committed sync."""
    data = await _get_board("ashby", slug, client)
    if data is None or data is NOT_MODIFIED:
        return data
    return [
        {
            "title": job.get("title"),
            "location": job.get("location"),
            "url": job.get("jobUrl"),
            "published_at": job.get("publishedAt"),
        }
        for job in jd_adapters.board_jobs(data, "ashby")
    ]


def greenhouse_url(slug: str, job: dict) -> str | None:
    """Use the canonical URL to select the ATS adapter; keep absolute_url for apply.
    Fall back to absolute_url when the posting has no id.
    """
    jid = job.get("id")
    if jid is None:
        return job.get("absolute_url")
    return f"https://job-boards.greenhouse.io/{slug}/jobs/{jid}"


async def fetch_greenhouse(slug: str, client=None) -> list[dict] | object | None:
    data = await _get_board("greenhouse", slug, client)
    if data is None or data is NOT_MODIFIED:
        return data
    return [
        {
            "title": job.get("title"),
            "location": job.get("location", {}).get("name") if isinstance(job.get("location"), dict) else job.get("location"),
            "url": greenhouse_url(slug, job),
            # A recent edit is not proof of a recent posting. Undated jobs are
            # excluded by the shared freshness policy, never stamped as new.
            "published_at": job.get("first_published"),
        }
        for job in jd_adapters.board_jobs(data, "greenhouse")
    ]


async def fetch_lever(slug: str, client=None) -> list[dict] | object | None:
    data = await _get_board("lever", slug, client)
    if data is None or data is NOT_MODIFIED:
        return data
    return [
        {
            "title": job.get("text"),
            "location": jd_adapters.object_field(job, "categories").get("location"),
            "url": job.get("hostedUrl"),
            "published_at": str(job["createdAt"]) if job.get("createdAt") else None,
        }
        for job in jd_adapters.board_jobs(data, "lever")
    ]


# T36: paged vendors. Those boards come in pages, often with no ETag, so a
# change check and a paging loop stand in for the one conditional GET above.
# Seconds between one board's pages; default 1. Eightfold 429s ~20-25% of
# requests whatever the pace (4/10 at 3 s, 10/50 at 6 s, 12/50 at 12 s), so a
# longer gap buys nothing: 6 s had the lowest rate, retries absorb the rest.
PAGE_GAP = {"eightfold": 6.0}
PAGE_RETRIES = (15, 30, 60)     # a mid-sweep 429 retries the page, it does not drop the board


class Partial(list):
    """Jobs from a board read only in part (a vendor's page cap). What is missing
    may be past the cap rather than closed, so sync closes nothing."""


def _page_of(data, key: str, ident: str) -> list[dict]:
    """A missing/malformed page is not evidence that postings closed."""
    items = data.get(key) if isinstance(data, dict) else None
    if not isinstance(items, list) or any(
            not isinstance(i, dict) or i.get(ident) is None or not str(i[ident]).strip() for i in items):
        raise ValueError(f"invalid board page: expected {key} with {ident}")
    return items


def _total(value) -> int:
    """A page's total, validated: a malformed one is the vendor's fault (a
    BoardVendorError), not a TypeError blamed on our code."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid board total: {value!r}")
    return value


async def _page(provider: str, fetch, *args):
    """One request of a many-page read, retried on a 429 or a transient failure
    (a timeout, a dropped connection, a 5xx): one blip used to throw away a
    whole read - a single ReadTimeout failed Micron's 100 pages."""
    for wait in PAGE_RETRIES:
        try:
            return await fetch(*args)
        except RateLimited as e:
            wait = min(e.retry_after, wait)
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                raise
        print(f"[board] {provider} request failed mid-board, retrying in {wait:.0f}s")
        await asyncio.sleep(wait)
    return await fetch(*args)


async def _read_board(provider: str, fetch_page, first, *, size: int, cap: int | None = None,
                      stale=None) -> tuple[list[dict], bool]:
    """Every page after `first` (items, total), in order. fetch_page(offset)
    returns (items, _). Stops at total, an empty page, the vendor's cap, or -
    only where the server sorts newest first - a page reaching past 14 days.
    Never asks past total: Workday wraps such offsets back to page 1.
    Returns (items, complete)."""
    items, total = first
    out, offset = list(items), size
    end = total if cap is None else min(total, cap)
    while items and offset < end and not (stale and any(map(stale, items))):
        await asyncio.sleep(PAGE_GAP.get(provider, 1.0))
        items, _ = await _page(provider, fetch_page, offset)
        out += items
        offset += size
    stopped_stale = bool(stale and items and any(map(stale, items)))
    # A posting closing mid-read shifts every later one up a place, so a live one
    # can slip past a page edge unseen: fewer items than the total means the
    # read cannot prove absence. (Full reads matched it: Adobe 582, Fiserv 356.)
    return out, (cap is None or total < cap) and (stopped_stale or len(out) >= end)


async def _first_pages(provider: str, slug: str, page, queries: list[tuple], ident: str):
    """Page 1 of each query (a site, a country...), skipping gone ones: None when
    all are gone, NOT_MODIFIED when nothing changed, else {query: (items, total)}.
    No ETag at these vendors, so page 1 stands in for one: each query's total
    plus its posting ids. A new posting changes page 1 or a total; a removal
    changes a total. ponytail: an add and a removal outside page 1 in the same
    interval go unseen until the board next changes."""
    firsts = {}
    for i, query in enumerate(queries):
        if i:
            await asyncio.sleep(PAGE_GAP.get(provider, 1.0))
        if (first := await _page(provider, page, *query, 0)) is not None:
            firsts[query] = first
    if not firsts:
        return None
    seen = [(query, total, [item[ident] for item in items]) for query, (items, total) in firsts.items()]
    fingerprint = hashlib.sha256(json.dumps(seen, default=str).encode()).hexdigest()
    _UNCOMMITTED_ETAGS[(provider, slug)] = fingerprint
    return NOT_MODIFIED if _ETAGS.get((provider, slug)) == fingerprint else firsts


def _days_ago(days: int | None) -> str | None:
    """Date-only vendors: N days back from now; N=0 is the moment we first saw it.
    sync never overwrites it later (DATE_ONLY), so a posting keeps that stamp."""
    return None if days is None else (board_policy.utcnow() - timedelta(days=max(days, 0))).isoformat()


def _age_days(day: str | None, fmt: str = "%Y-%m-%d") -> int | None:
    try:
        return (board_policy.utcnow().date() - datetime.strptime(day, fmt).date()).days
    except (TypeError, ValueError):
        return None


def _alpha2(code) -> str | None:
    """A vendor-stated ISO country (Oracle "US", SmartRecruiters "us"), for is_target_location."""
    return code.upper() if isinstance(code, str) and re.fullmatch(r"[A-Za-z]{2}", code) else None


def _older_than_window(when: datetime | None) -> bool:
    return when is not None and when <= board_policy.utcnow() - board_policy.MAX_AGE


# Every relative form seen in 30k postings (2026-09-24). "30+ Days Ago" is a
# lower bound, not a date, so it stays undated (and ineligible).
_WORKDAY_POSTED = re.compile(r"Posted (Today|Yesterday|(\d+) Days? Ago)")
_N_LOCATIONS = re.compile(r"\d+ Locations")
# 404, 422 (not on that wdN host) and a JSON 403 (S22, a private site) all mean gone
WORKDAY_GONE = (403, 404, 422)
_WORKDAY_DETAILS: dict[str, tuple] = {}  # job URL -> (locations, country, start date), from the detail call
# T43: board -> the country filter that brings a capped site under the cap, or
# None when none fits (Walmart: its US view alone overflows). Relearnt after a restart.
_WORKDAY_FILTERS: dict[str, dict | None] = {}


def _country_ids(facets) -> list[str]:
    """The `locationCountry` values our own location filter accepts - US, Canada
    and places it keeps, like Puerto Rico (US+CA alone lost ABB's Arecibo job) -
    at the top level or nested, as Accenture nests them under locationMainGroup."""
    ids = []
    for f in facets if isinstance(facets, list) else []:
        if not isinstance(f, dict):
            continue
        values = [v for v in f.get("values") or [] if isinstance(v, dict)]
        if f.get("facetParameter") == "locationCountry":
            ids += [v["id"] for v in values if isinstance(v.get("id"), str) and isinstance(v.get("descriptor"), str)
                    and is_target_location(v["descriptor"])]
        else:
            ids += _country_ids(values)
    return ids


def workday_days(posted_on) -> int | None:
    m = _WORKDAY_POSTED.fullmatch(posted_on) if isinstance(posted_on, str) else None
    if not m:
        return None
    return {"Today": 0, "Yesterday": 1}.get(m.group(1)) if m.group(2) is None else int(m.group(2))


async def _workday_detail(client, wd, url: str) -> tuple[str | None, str | None, str | None]:
    """(every location, the primary one's ISO country, the posting date) from the
    detail call. A list row may say only "4 Locations", or a code like "TUN -
    ARIANA" or "SGP Work-at-Home" that no location rule can read; the detail
    names them all and states the primary country (verified on 5 tenants). And
    6 of 315 sites send no readable postedOn at all; the detail has startDate."""
    if url not in _WORKDAY_DETAILS:
        await asyncio.sleep(PAGE_GAP.get("workday", 1.0))
        body = await _page("workday", functools.partial(_download, gone=WORKDAY_GONE), client, wd.api_url(url))
        info = jd_adapters.object_field(json.loads(body), "jobPostingInfo") if body else {}
        places = [info.get("location"), *(info.get("additionalLocations") or [])]
        country = jd_adapters.object_field(jd_adapters.object_field(info, "jobRequisitionLocation"),
                                           "country").get("alpha2Code")
        start = info.get("startDate")
        _WORKDAY_DETAILS[url] = (" | ".join(p for p in places if isinstance(p, str) and p.strip()) or None,
                                 country if isinstance(country, str) and country else None,
                                 start if isinstance(start, str) else None)
    return _WORKDAY_DETAILS[url]


async def fetch_workday(slug: str, client, boards: list[str]) -> list[dict] | object | None:
    """All of a company's Workday sites, merged. Their order is set per company
    and is not by date (stopping at the first stale page lost 529 of Cisco's 570
    fresh jobs), so a changed board is read to its end - which Workday caps at
    2000 (29 of 405 sites), unless the countries we keep fit under it (T43)."""
    wd = jd_adapters.by_name("workday")

    async def fetch(board: str, offset: int, facets: dict | None):
        url, body = wd.list_request(board, offset, facets)
        data = await _download(client, url, body=body, gone=WORKDAY_GONE)
        if data is None:
            if offset:
                raise ValueError(f"workday {board} vanished mid-read")
            return None  # 404/422/403-S22: this site is gone
        data = json.loads(data)
        jobs = data.get("jobPostings") if isinstance(data, dict) else None
        if not isinstance(jobs, list) or any(not isinstance(j, dict) for j in jobs):
            raise ValueError("invalid workday board: expected jobPostings")
        # Adobe lists a row with only bulletFields (2026-09-24): skipped, and the
        # read then falls short of its total, so nothing is closed on it.
        jobs = [j for j in jobs if isinstance(j.get("externalPath"), str) and j["externalPath"].strip()]
        return jobs, _total(data.get("total")), data.get("facets")  # total and facets: page 1 only

    async def page(board: str, offset: int):
        got = await fetch(board, offset, _WORKDAY_FILTERS.get(board))
        if got is None or offset or board in _WORKDAY_FILTERS or got[1] < wd.CAP:
            return got and got[:2]
        # A capped site, seen from the countries we keep: Accenture's 6 missed
        # recent jobs sat past row 2,000, and its US/CA view is 926 rows - which the
        # fingerprint then watches. Remembered once asked, so a failed ask is retried.
        ids, fit = _country_ids(got[2]), None
        if ids:
            await asyncio.sleep(PAGE_GAP.get("workday", 1.0))
            narrowed = await fetch(board, 0, {"locationCountry": ids})
            if narrowed and narrowed[1] < wd.CAP:
                got, fit = narrowed, {"locationCountry": ids}
        _WORKDAY_FILTERS[board] = fit
        return got[:2]

    firsts = await _first_pages("workday", slug, page, [(b,) for b in boards], "externalPath")
    if firsts is None or firsts is NOT_MODIFIED:
        return firsts
    jobs, complete, seen = [], True, set()
    for (board,), first in firsts.items():
        items, whole = await _read_board("workday", functools.partial(page, board), first,
                                         size=wd.PAGE, cap=wd.CAP)
        complete = complete and whole
        for job in items:
            if job["externalPath"] in seen:  # one job listed on two of the company's sites
                continue
            seen.add(job["externalPath"])
            url, location = wd.job_url(board, job["externalPath"]), job.get("locationsText")
            posted = job.get("postedOn")
            days, country = workday_days(posted), None
            undated = not (isinstance(posted, str) and posted.startswith("Posted "))
            # None too: Accenture lists every row without one (531 foreign jobs got in).
            unreadable = not isinstance(location, str) or (
                _N_LOCATIONS.fullmatch(location) or location_kinds(location) <= {"unknown"})
            if (isinstance(job.get("title"), str) and is_target_role(job["title"])
                    and (undated or (unreadable and days is not None and days < board_policy.MAX_AGE.days))):
                named, country, start = await _workday_detail(client, wd, url)
                location = named or location
                if undated:
                    days = _age_days(start)
            jobs.append({"title": job.get("title"), "location": location, "url": url,
                         "published_at": _days_ago(days), "country": country})
    return jobs if complete else Partial(jobs)


MAX_CONFIRM = 50  # detail calls per sync; ponytail: the rest are confirmed on the next one


async def _confirmed_gone(db, company: TrackedCompany, jobs: list[dict], client) -> set[str]:
    """A partial read (a cap, ghost rows, postings closing mid-read - Cisco read
    short on every try) cannot prove a posting gone by its absence, so ask the
    vendor about each stored one it did not see. Workday answers a closed job
    with a JSON 403 S22 (9 of 10 closed postings). Runs before sync writes, so
    no SQLite write lock is held across these requests."""
    if company.provider != "workday":
        return set()
    with db.no_autoflush:
        stored = db.scalars(select(JobPosting.url).where(
            JobPosting.company_slug == company.slug, JobPosting.status == "open")).all()
    seen, wd, gone = {job.get("url") for job in jobs}, jd_adapters.by_name("workday"), set()
    for url in [u for u in stored if u not in seen][:MAX_CONFIRM]:
        await asyncio.sleep(PAGE_GAP.get("workday", 1.0))
        detail = functools.partial(_download, gone=WORKDAY_GONE)
        if await _page("workday", detail, client, wd.api_url(url)) is None:
            gone.add(url)
    return gone


async def fetch_oracle(slug: str, client, boards: list[str]) -> list[dict] | object | None:
    """Oracle sorts newest first on the server (0 inversions in full reads of
    all 3 boards, 3,462 postings), so reading stops past 14 days."""
    orc = jd_adapters.by_name("oracle")

    async def page(board: str, offset: int):
        data = await _download(client, orc.list_url(board, offset))
        if data is None:
            if offset:
                raise ValueError(f"oracle {board} vanished mid-read")
            return None
        search = _page_of(json.loads(data), "items", "SearchId")
        if len(search) != 1:
            raise ValueError("invalid oracle board: expected one search")
        return _page_of(search[0], "requisitionList", "Id"), _total(search[0].get("TotalJobsCount"))

    def stale(req: dict) -> bool:
        days = _age_days(req.get("PostedDate"))
        return days is not None and days >= board_policy.MAX_AGE.days

    firsts = await _first_pages("oracle", slug, page, [(b,) for b in boards], "Id")
    if firsts is None or firsts is NOT_MODIFIED:
        return firsts
    jobs = []
    for (board,), first in firsts.items():
        items, _ = await _read_board("oracle", functools.partial(page, board), first, size=orc.PAGE, stale=stale)
        for req in items:
            places = [req.get("PrimaryLocation"), *(loc.get("Name") for loc in req.get("secondaryLocations") or []
                                                    if isinstance(loc, dict))]
            jobs.append({"title": req.get("Title"), "url": orc.job_url(board, req["Id"]),
                         "location": " | ".join(p for p in places if isinstance(p, str) and p.strip()) or None,
                         "published_at": _days_ago(_age_days(req.get("PostedDate"))),
                         "country": _alpha2(req.get("PrimaryLocationCountry"))})
    return jobs


async def fetch_smartrecruiters(slug: str, client=None) -> list[dict] | object | None:
    """Newest first (0 inversions in full reads of all 3 boards, 1,271 postings).
    An unknown company is a 200 with no postings, never a 404 (verified)."""
    sr = jd_adapters.by_name("smartrecruiters")

    async def page(offset: int):
        data = await _download(client, sr.list_url(slug, offset))
        if data is None:
            raise ValueError(f"smartrecruiters/{slug} vanished mid-read")
        data = json.loads(data)
        return _page_of(data, "content", "id"), _total(data.get("totalFound"))

    firsts = await _first_pages("smartrecruiters", slug, page, [()], "id")
    if firsts is NOT_MODIFIED:
        return firsts
    items, _ = await _read_board("smartrecruiters", page, firsts[()], size=sr.PAGE,
                                 stale=lambda j: _older_than_window(jd_adapters.parse_ats_date(j.get("releasedDate"))))
    return [{"title": j.get("name"),
             "location": jd_adapters.object_field(j, "location").get("fullLocation"),
             "country": _alpha2(jd_adapters.object_field(j, "location").get("country")),  # "us"
             "url": sr.job_url(jd_adapters.object_field(j, "company").get("identifier") or slug, j["id"]),
             "published_at": j.get("releasedDate")} for j in items]


async def fetch_eightfold(slug: str, client, boards: list[str]) -> list[dict] | object | None:
    """US and Canada only (Microsoft 2,432 -> 1,233 for the US). Not strictly
    newest first, so every page is read. Eightfold 429s often (see PAGE_GAP),
    so every page retries."""
    ef = jd_adapters.by_name("eightfold")
    queries = [(board, place) for board in boards for place in ("United States", "Canada")]

    async def page(board: str, place: str, start: int):
        data = await _download(client, ef.list_url(board, place, start))
        if data is None:
            if start:
                raise ValueError(f"eightfold {board} vanished mid-read")
            return None
        data = jd_adapters.object_field(json.loads(data), "data")
        return _page_of(data, "positions", "id"), _total(data.get("count"))

    firsts = await _first_pages("eightfold", slug, page, queries, "id")
    if firsts is None or firsts is NOT_MODIFIED:
        return firsts
    jobs, seen = [], set()
    for (board, place), first in firsts.items():
        items, _ = await _read_board("eightfold", functools.partial(page, board, place), first, size=ef.PAGE)
        for p in items:
            if p["id"] in seen:  # a job in both countries
                continue
            seen.add(p["id"])
            locations = [x for x in p.get("locations") or [] if isinstance(x, str)]
            jobs.append({"title": p.get("name"), "location": " | ".join(locations) or None,
                         "url": ef.job_url(board, p["id"]),
                         "published_at": jd_adapters.epoch_seconds(p.get("postedTs"))})
    return jobs


AMAZON_CAP = 10_000  # `hits` of an unfiltered search stops here


async def fetch_amazon(slug: str, client=None) -> list[dict] | object | None:
    """Software development roles in the US and Canada (1,751 in the US on
    2026-09-24). `sort=recent` is not strictly by date, so every page is read."""
    amz = jd_adapters.by_name("amazon")

    async def page(country: str, offset: int):
        data = await _download(client, amz.list_url(country, offset))
        if data is None:
            raise ValueError(f"amazon {country} search is gone")
        data = json.loads(data)
        return _page_of(data, "jobs", "job_path"), _total(data.get("hits"))

    firsts = await _first_pages("amazon", slug, page, [("USA",), ("CAN",)], "job_path")
    if firsts is NOT_MODIFIED:
        return firsts
    jobs, complete = [], True
    for (country,), first in firsts.items():
        items, whole = await _read_board("amazon", functools.partial(page, country), first,
                                         size=amz.PAGE, cap=AMAZON_CAP)
        complete = complete and whole
        jobs += [{"title": j.get("title"), "location": j.get("normalized_location") or j.get("location"),
                  "url": amz.job_url(j["job_path"]),
                  "published_at": _days_ago(_age_days(j.get("posted_date"), "%B %d, %Y"))} for j in items]
    return jobs if complete else Partial(jobs)


async def fetch_apple(slug: str, client=None) -> list[dict] | object | None:
    """Newest first on the server (0 inversions in a full read of all 4,574 US
    postings), so reading stops past 14 days: ~37 of 229 pages. Data comes
    embedded in the search page's HTML."""
    apple = jd_adapters.by_name("apple")

    async def page(location: str, offset: int):
        data = await _download(client, apple.list_url(location, offset // apple.PAGE + 1))
        if data is None:
            raise ValueError(f"apple {location} search is gone")
        search = jd_adapters.object_field(jd_adapters.apple_data(data.decode("utf-8", "replace")), "search")
        return _page_of(search, "searchResults", "positionId"), _total(search.get("totalRecords"))

    # both verified: Apple echoes the location filter back
    firsts = await _first_pages("apple", slug, page, [("united-states-USA",), ("canada-CANC",)], "positionId")
    if firsts is NOT_MODIFIED:
        return firsts
    jobs = []
    for (location,), first in firsts.items():
        items, _ = await _read_board(
            "apple", functools.partial(page, location), first, size=apple.PAGE,
            stale=lambda j: _older_than_window(jd_adapters.parse_ats_date(j.get("postDateInGMT"))))
        jobs += [{"title": j.get("postingTitle"), "location": jd_adapters.apple_location(j.get("locations")),
                  "url": apple.job_url(j["positionId"]), "published_at": j.get("postDateInGMT")} for j in items]
    return jobs


async def fetch_workable(slug: str, client=None) -> list[dict] | object | None:
    """One request holds every job, a multi-location job once per location
    (charlotte-tilbury: 301 rows, 270 jobs = the paged search's total), so
    rows merge by shortcode. An unknown account is a 404 (verified)."""
    wk = jd_adapters.by_name("workable")
    data = await _get_board("workable", slug, client)
    if data is None or data is NOT_MODIFIED:
        return data
    merged: dict[str, list[dict]] = {}
    for row in _page_of(data, "jobs", "shortcode"):
        merged.setdefault(str(row["shortcode"]), []).append(row)
    jobs = []
    for shortcode, rows in merged.items():
        spots = [spot for row in rows for spot in row.get("locations") or [
            {"city": row.get("city"), "region": row.get("state"), "country": row.get("country")}]
            if isinstance(spot, dict) and not spot.get("hidden")]  # 10 of 4,744 live: the employer hid them
        location, _ = jd_adapters.places(spots, "city", "region", "country", "countryCode")
        codes = {spot.get("countryCode") for spot in spots}
        jobs.append({"title": rows[0].get("title"), "location": location, "url": wk.job_url(slug, shortcode),
                     "published_at": _days_ago(_age_days(rows[0].get("published_on"))),
                     "country": _alpha2(codes.pop()) if len(codes) == 1 else None})
    return jobs


# A posting was dated up to 6 days after its sitemap lastmod (8 of 134 checked),
# so a job is a candidate if touched within the window plus a 30-day margin.
ICIMS_WINDOW = board_policy.MAX_AGE + timedelta(days=30)
_ROBOTS: dict[str, tuple[datetime, RobotFileParser]] = {}  # host -> (read at, rules)
_ICIMS_POSTINGS: dict[str, dict] = {}  # job URL -> fields from its JSON-LD


async def _robots(client, url: str) -> RobotFileParser:
    """A site's robots.txt, re-read daily; a missing one (404) allows everything."""
    host, now = urlparse(url).hostname, board_policy.utcnow()
    if host not in _ROBOTS or _ROBOTS[host][0] <= now - timedelta(days=1):
        body = await _page("icims", _download, client, url)
        rules = RobotFileParser()
        rules.parse((body or b"").decode("utf-8", "replace").splitlines())
        _ROBOTS[host] = (now, rules)
    return _ROBOTS[host][1]


async def _icims_posting(client, ic, url: str, gap: float) -> dict | None:
    """The job's own JSON-LD: None when the job is gone (410, verified), {} when
    its page carries none - not cached, as that may be a passing error page
    (0 of 134 real pages lacked it)."""
    if url not in _ICIMS_POSTINGS:
        await asyncio.sleep(gap)
        page = await _page("icims", functools.partial(_download, gone=(404, 410)), client, ic.api_url(url))
        if page is None:
            return None
        posting = jd_adapters.job_posting(page.decode("utf-8", "replace"))
        if not posting:
            return {}
        location, country = jd_adapters.posting_places(posting)
        faked = ic.faked(posting, board_policy.utcnow())
        _ICIMS_POSTINGS[url] = {
            "title": posting.get("title"), "location": location, "country": _alpha2(country),
            "published_at": None if faked else _days_ago(_age_days(str(posting.get("datePosted") or "")[:10]))}
    return _ICIMS_POSTINGS[url]


async def fetch_icims(slug: str, client, boards: list[str]) -> list[dict] | None:
    """A portal's sitemap lists every open job (it matched the search total on 4
    portals: 669, 1,512, 65, 39) but only a title in the URL, and its lastmod
    is not the posting date. So the likely target roles are read from their
    own page's JSON-LD; the rest are seen, never stored. robots.txt is per
    portal (3 of 70 active ones forbid us): a portal that does is gone.
    Where that page fakes or lacks its date (T41), a job newer by id than every
    job left untouched for 14 days is dated by its lastmod: a job is never
    edited before it exists, and ids run in posting order. On the 74 real
    portals this matched the true date at 85% precision; lastmod alone, 58%
    (edits move it)."""
    ic = jd_adapters.by_name("icims")
    jobs, live = [], False
    for board in boards:
        rules = await _robots(client, ic.robots_url(board))
        if not rules.can_fetch(USER_AGENT, ic.sitemap_url(board)):
            print(f"[board] icims {board}: robots.txt forbids us")
            continue
        body = await _page("icims", _download, client, ic.sitemap_url(board))
        if body is None:
            continue
        sitemap = body.decode("utf-8", "replace")
        if "<urlset" not in sitemap:  # an error page or an index is not proof every job closed
            raise ValueError(f"icims {board}: sitemap is not a urlset")
        live, host = True, ic.board(board).split("//")[1]
        gap = max(PAGE_GAP.get("icims", 1.0), rules.crawl_delay(USER_AGENT) or 0)
        now, entries = board_policy.utcnow(), []
        for loc, lastmod in re.findall(r"<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", sitemap):
            url = html.unescape(loc).strip()
            if ic.match(url) and ic.board_of(url)[1] == f"https://{host}":  # not other pages or a stray host
                entries.append((url, jd_adapters.parse_ats_date(lastmod), lastmod))
        old = max((ic.job_id(u) for u, t, _ in entries if t and t <= now - board_policy.MAX_AGE), default=None)
        for url, touched, lastmod in entries:
            title, posting = ic.slug_title(url), {}
            if (is_target_role(title) and (touched is None or touched > now - ICIMS_WINDOW)
                    and rules.can_fetch(USER_AGENT, ic.api_url(url))):
                posting = await _icims_posting(client, ic, url, gap)
                if posting is None:
                    continue  # closed since the sitemap was built
                if posting and posting["published_at"] is None and old is not None and ic.job_id(url) > old:
                    # its own calendar day, as for datePosted above (FTI: 20:59 -04:00 is that day)
                    posting = {**posting, "published_at": _days_ago(_age_days(lastmod[:10]))}
            jobs.append({"title": title, "location": None, "published_at": None, **posting, "url": url})
    return jobs if live else None


class BoardVendorError(Exception):
    """The vendor's board could not be fetched or parsed. Expected noise, not a
    bug in our code - the distinction is the whole point of this exception."""


FETCHERS = {"ashby": fetch_ashby, "greenhouse": fetch_greenhouse, "lever": fetch_lever,
            "workday": fetch_workday, "oracle": fetch_oracle, "smartrecruiters": fetch_smartrecruiters,
            "eightfold": fetch_eightfold, "amazon": fetch_amazon, "apple": fetch_apple,
            "workable": fetch_workable, "icims": fetch_icims}
NEEDS_BOARDS = {"workday", "oracle", "eightfold", "icims"}  # a slug alone does not locate these
# Only these 404 a slug they do not host, which is what makes the move check
# sound; SmartRecruiters answers 200 for any slug (verified), the rest need boards.
# Not Workable: it 404s unknown accounts, but 15 of 16 parked slugs it knew were
# dormant accounts with 0 jobs - a move there would never be rechecked.
MOVABLE = ("greenhouse", "lever", "ashby")
# Vendors that give only a date: their first-seen stamp is kept, never recomputed.
DATE_ONLY = {"workday", "oracle", "amazon", "workable", "icims"}
WORKERS = {"workday": 3}  # 8,833 pages if all ~315 sites changed: 2.5-3.7 h on one lane


def discovery_delays(db, days: int) -> dict:
    """T46: minutes from posting to our first sight, per vendor, over jobs first
    seen in the last `days`. Left out: date-only vendors (their post time is our
    own first sight) and what was already on a board when we first read it - a
    job counts only if posted after its company's earliest first sight - and
    not after our own first sight (exact-date vendors rewrite created_at each read,
    so a re-dated job would read negative). Lever's createdAt is creation, which
    can precede publishing. Nearest-rank percentiles."""
    watching = (select(JobPosting.company_slug, func.min(JobPosting.first_seen_at).label("since"))
                .group_by(JobPosting.company_slug).subquery())
    rows = db.execute(
        select(TrackedCompany.provider, JobPosting.created_at, JobPosting.first_seen_at)
        .join(TrackedCompany, TrackedCompany.slug == JobPosting.company_slug)
        .join(watching, watching.c.company_slug == JobPosting.company_slug)
        .where(JobPosting.first_seen_at >= board_policy.utcnow() - timedelta(days=days),
               JobPosting.created_at > watching.c.since, JobPosting.created_at <= JobPosting.first_seen_at,
               TrackedCompany.provider.not_in(DATE_ONLY)))
    delays: dict[str, list[float]] = {}
    for provider, posted, seen in rows:
        delays.setdefault(provider, []).append((seen - posted).total_seconds() / 60)
    rank = lambda xs, q: round(xs[math.ceil(q * len(xs)) - 1])
    return {"days": days, "vendors": {
        provider: {"jobs": len(xs), "p50_minutes": rank(xs, 0.5), "p95_minutes": rank(xs, 0.95),
                   "max_minutes": round(xs[-1])}
        for provider, xs in ((p, sorted(v)) for p, v in sorted(delays.items()))}}


async def _fetch(provider: str, slug: str, client=None, boards: list[str] | None = None):
    fetch = FETCHERS.get(provider)
    if fetch is None:
        raise BoardVendorError(f"unknown provider {provider!r}")
    try:
        if provider in NEEDS_BOARDS:
            if not boards:
                raise ValueError("no board URL recorded")
            return await fetch(slug, client, boards)
        return await fetch(slug, client)
    except (httpx.HTTPError, ValueError) as e:
        # the type too: an httpx timeout's message is often empty (T30: 6 blank log lines)
        raise BoardVendorError(f"{provider}/{slug}: {type(e).__name__}: {e}") from e


async def _find_moved_board(company: TrackedCompany, client=None) -> list[dict] | None:
    """Companies change ATS. T29 audit: 103 of 348 boards that 404'd were live on
    another vendor under the same slug (Notion, Sentry, Zapier...), and none on
    two. All three vendors 404 a slug they do not host, so a 200 is evidence.
    ponytail: same slug is taken as same company; the vendors expose no stronger
    identity. Worst case is a real board of a same-named company."""
    for provider in MOVABLE:
        if provider == company.provider:
            continue
        _ETAGS.pop((provider, company.slug), None)  # a 304 here would carry no jobs
        try:
            jobs = await _fetch(provider, company.slug, client)
        except BoardVendorError:
            continue
        if jobs is not None:
            print(f"[board] {company.slug} moved {company.provider} -> {provider}")
            company.provider = provider
            return jobs
    return None


async def sync_company_jobs(db, company: TrackedCompany, client=None) -> int | None:
    """Refresh one company's postings and return how many were kept, or None
    when the board is unchanged since its last committed sync (304).
    Raise BoardVendorError/RateLimited for vendor failures; let code bugs propagate.
    """
    raw_jobs = await _fetch(company.provider, company.slug, client, company.boards)
    if raw_jobs is None and company.provider in MOVABLE:
        # Not for a board-URL vendor: a Workday outage would read as a move to
        # whatever same-named board another vendor happens to host.
        raw_jobs = await _find_moved_board(company, client)
    gone = await _confirmed_gone(db, company, raw_jobs, client) if isinstance(raw_jobs, Partial) else set()

    now = board_policy.utcnow()
    company.last_synced_at = now
    if raw_jobs is None:
        # 404 everywhere: we did not observe this board, so we cannot conclude
        # its postings are gone. Closing them here would wipe a company's whole
        # feed on a transient outage; they expire by publication age instead.
        # An empty 200 is different - that we DID observe. Park, recheck weekly.
        company.gone_at, company.next_check_at = now, now + PARK_FOR
        db.commit()
        return 0
    company.gone_at = None
    if raw_jobs is NOT_MODIFIED:
        _reschedule(company, now, lists_target=None, new_jobs=0)
        db.commit()
        return None

    was_open = set(db.scalars(select(JobPosting.url).where(
        JobPosting.company_slug == company.slug, JobPosting.status == "open")))
    lists_target = False
    active_urls = []
    expired_urls = []
    for job in raw_jobs:
        if not job.get("title") or not job.get("url"):
            continue
        matches = is_target_role(job["title"]) and is_target_location(job["location"], job.get("country"))
        lists_target = lists_target or matches
        posted_dt = parse_ats_date(job.get("published_at"))
        if not board_policy.is_recent(posted_dt, now):
            # A legacy stored edit timestamp can look fresh. Once a normal
            # harvest establishes an ineligible date, do not retain that row.
            expired_urls.append(job["url"])
            continue
        if not matches:
            continue
        active_urls.append(job["url"])
        fields = {"title": job["title"], "location": job["location"],
                  "status": "open", "created_at": posted_dt, "updated_at": now}
        # A date-only vendor's stamp was fixed when we first saw the posting.
        kept = {k: v for k, v in fields.items() if k != "created_at"} \
            if company.provider in DATE_ONLY else fields
        db.execute(
            insert(JobPosting)
            # first_seen_at only here, never in `kept`: set once, on the first sight (T46)
            .values(url=job["url"], company_slug=company.slug, first_seen_at=now, **fields)
            .on_conflict_do_update(index_elements=["url"], set_=kept)
        )

    # Batch expired rows without exceeding older SQLite parameter limits.
    for start in range(0, len(expired_urls), 500):
        db.execute(delete(JobPosting).where(
            JobPosting.company_slug == company.slug,
            JobPosting.url.in_(expired_urls[start:start + 500]),
        ))

    # Listings absent from a valid board are closed until publication-age expiry.
    closing = (
        JobPosting.__table__.update()
        .where(JobPosting.company_slug == company.slug)
        .where(JobPosting.status != "closed")
        .values(status="closed", updated_at=now)
    )
    keep = set(active_urls)
    if isinstance(raw_jobs, Partial):
        # Absence proves nothing here: close only what was seen but no longer
        # matches, and what the vendor confirmed gone.
        seen = {job.get("url") for job in raw_jobs}
        keep |= {url for url in was_open if url not in seen and url not in gone}
    if keep:
        closing = closing.where(JobPosting.url.not_in(keep))
    db.execute(closing)

    _reschedule(company, now, lists_target=lists_target, new_jobs=len(set(active_urls) - was_open))
    db.commit()
    _commit_etag(company.provider, company.slug)
    return len(active_urls)


def _is_peak(now: datetime) -> bool:
    return now.hour >= 13 or now.hour < 1


def next_interval(current: timedelta, *, lists_target: bool | None, new_jobs: int, peak: bool) -> timedelta:
    """The revisit rule. lists_target=None means a 304 (nothing to judge by):
    quiet boards sit exactly on QUIET_INTERVAL, so the interval itself says
    which kind a board is and needs no extra column. Compared against QUIET,
    not ACTIVE_CEILING, so changing the ceiling can't reclassify boards.

    A board that lists our roles lands on about a minute. Quiet boards stay
    daily. Growth still only happens at peak, and never past the ceiling."""
    if lists_target is None:
        lists_target = current < QUIET_INTERVAL
    if not lists_target:
        return QUIET_INTERVAL
    current = min(current, ACTIVE_CEILING)
    if new_jobs:
        return max(current * 0.5, MIN_INTERVAL)   # ours: Nutch's x0.8 is for any change
    return min(current * 1.2, ACTIVE_CEILING) if peak else current  # Nutch's default x1.2


def _reschedule(company: TrackedCompany, now: datetime, *, lists_target: bool | None, new_jobs: int) -> None:
    current = timedelta(seconds=company.check_interval or HARVEST_INTERVAL.total_seconds())
    interval = next_interval(current, lists_target=lists_target, new_jobs=new_jobs, peak=_is_peak(now))
    company.check_interval = int(interval.total_seconds())
    company.next_check_at = now + (interval if _is_peak(now) else max(interval, NIGHT_FLOOR))


def _strained(error: BoardVendorError) -> bool:
    """The vendor itself is struggling (5xx, timeouts, dropped connections) - as
    opposed to a 4xx, a malformed board or an unknown provider, which say nothing
    about its load. A 429/403 is RateLimited and handled by the lane directly."""
    cause = error.__cause__
    return isinstance(cause, httpx.TransportError) or (
        isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code >= 500)


def _new_stats() -> dict:
    return dict.fromkeys(("companies", "kept", "unchanged", "vendor_errors", "rate_limited",
                          "bugs", "max_lag"), 0)


def _is_priority(company: TrackedCompany) -> bool:
    """Already lists our roles: its interval sits under the daily quiet watch."""
    return company.check_interval is not None and company.check_interval < int(QUIET_INTERVAL.total_seconds())


def _next_due(db, provider: str, now: datetime, *, wide: bool = False) -> TrackedCompany | None:
    """The next board this vendor should check.

    A pasted board (no next_check_at) still goes first. Then a board that
    already lists our roles, most overdue first. A Wayback or Simplify import
    leaves thousands of never-checked boards with next_check_at in the past;
    oldest-first spent the whole lane on that cold backlog and left hiring
    boards (Discord, Anthropic) unchecked for a day. wide=True takes one due
    quiet or never-checked board so that set keeps moving, then falls back to
    the priority order when nothing in it is due.
    """
    due = or_(TrackedCompany.next_check_at.is_(None), TrackedCompany.next_check_at <= now)
    hiring = TrackedCompany.check_interval < int(QUIET_INTERVAL.total_seconds())
    if wide:
        cold = db.scalars(
            select(TrackedCompany).where(
                TrackedCompany.provider == provider,
                TrackedCompany.next_check_at.is_not(None),
                TrackedCompany.next_check_at <= now,
                or_(TrackedCompany.check_interval.is_(None),
                    TrackedCompany.check_interval >= int(QUIET_INTERVAL.total_seconds())),
            ).order_by(TrackedCompany.next_check_at.asc()).limit(1)
        ).first()
        if cold is not None:
            return cold
    return db.scalars(
        select(TrackedCompany).where(TrackedCompany.provider == provider, due).order_by(
            case((TrackedCompany.next_check_at.is_(None), 0), else_=1),
            case((hiring, 0), else_=1),
            TrackedCompany.next_check_at.asc(),
        ).limit(1)
    ).first()


async def _vendor_worker(provider: str, stats: dict, *, drain: bool = False,
                         report_every: float | None = None) -> None:
    """One vendor's queue of the URL frontier (T31): a pasted or newly found
    board is picked up within seconds, then boards that already list our roles,
    then the cold backlog. One at a time with a paced gap. Politeness is per
    host - three workers run side by side and each vendor still gets requests
    at least JITTER[0] apart. Like Googlebot, it widens its gap when the vendor
    strains (429/5xx/timeouts) and narrows it again on success. drain=True
    returns once nothing is due (tests, one-shot runs). report_every prints a
    health line that often - if max_lag keeps growing, this vendor is over its
    request budget."""
    slowdown = 1.0
    last_report = time.monotonic()
    priority_streak = 0
    async with httpx.AsyncClient(timeout=BOARD_TIMEOUT) as client:
        while True:
            if report_every is not None and time.monotonic() - last_report >= report_every:
                _report(stats, provider)
                stats.update(_new_stats())
                last_report = time.monotonic()
            with _db.SessionLocal() as db:
                now = board_policy.utcnow()
                of_vendor = TrackedCompany.provider == provider
                company = _next_due(db, provider, now, wide=priority_streak >= WIDE_EVERY)
                if company is not None:
                    # A wide turn, or anything that is not a hiring board, restarts
                    # the burst so priority boards are never stuck behind the import.
                    priority_streak = 0 if (
                        priority_streak >= WIDE_EVERY or not _is_priority(company)) else priority_streak + 1
                if company is None:
                    if drain:
                        return
                    upcoming = db.scalar(select(func.min(TrackedCompany.next_check_at)).where(of_vendor))
                    idle = WORKER_IDLE if upcoming is None else (upcoming - now).total_seconds()
                else:
                    stats["companies"] += 1
                    if company.next_check_at is not None:
                        stats["max_lag"] = max(stats["max_lag"], (now - company.next_check_at).total_seconds())
                    # Book the next attempt before fetching and outside the rollback
                    # below: a failing board waits its interval like any other.
                    company.last_synced_at = now
                    company.next_check_at = now + timedelta(
                        seconds=company.check_interval or HARVEST_INTERVAL.total_seconds())
                    db.commit()
                    strained = False
                    try:
                        kept = await sync_company_jobs(db, company, client)
                        if kept is None:
                            stats["unchanged"] += 1
                        else:
                            stats["kept"] += kept
                    except RateLimited as e:
                        db.rollback()
                        strained = True
                        stats["rate_limited"] += 1
                        wait = min(e.retry_after, MAX_BACKOFF)
                        print(f"[board] {provider} asked us to back off {wait:.0f}s")
                        await asyncio.sleep(wait)
                    except BoardVendorError as e:
                        db.rollback()
                        strained = _strained(e)
                        stats["vendor_errors"] += 1
                        print(f"[board] vendor problem: {e}")
                    except Exception:
                        db.rollback()
                        stats["bugs"] += 1
                        if stats["bugs"] == 1:  # one traceback is a signal, 900 is noise
                            traceback.print_exc()
            if company is None:
                await asyncio.sleep(min(WORKER_IDLE, max(idle, 0.0)))
                continue
            slowdown = min(slowdown * 2, MAX_SLOWDOWN) if strained else max(slowdown / 2, 1.0)
            await asyncio.sleep(random.uniform(*JITTER) * slowdown)


def _report(stats: dict, label: str) -> None:
    if stats["bugs"]:
        print(f"[board] ERROR {stats['bugs']} companies failed on OUR code, not the vendor's")
    if stats["companies"]:  # an idle window has nothing to say
        print(f"[board] {label}: {stats}")


async def _harvest_cycle() -> dict:
    """Check every due board once, all vendors side by side, then return the
    counters (tests and one-shot runs; the server runs harvester_loop)."""
    stats = _new_stats()
    with _db.SessionLocal() as db:
        seed_db_if_empty(db)
        track_f500(db)
    await asyncio.gather(*(_vendor_worker(provider, stats, drain=True) for provider in _lanes()))
    # Whole-feed check only: one quiet vendor window keeping nothing is normal now
    # that most tracked boards list none of our roles (T31).
    if stats["companies"] and not stats["kept"] and not stats["unchanged"]:
        print("[board] no eligible postings in the last 14 days; see vendor_errors/bugs above")
    _report(stats, "cycle done")
    return stats


async def _worker_forever(provider: str) -> None:
    stats = _new_stats()
    while True:
        try:
            await _vendor_worker(provider, stats, report_every=HEALTH_EVERY)
        except Exception:  # e.g. the DB briefly unavailable: never let a vendor go dark
            _log_exc()  # print_exc itself raises if stderr's reader is gone
            await asyncio.sleep(WORKER_IDLE)


def _lanes() -> list[str]:
    """One worker per vendor, more where one cannot keep up (WORKERS). Safe:
    a worker books its board (select, set next_check_at, commit) with no await
    in between, so two workers of one vendor never pick the same board."""
    return [provider for provider in FETCHERS for _ in range(WORKERS.get(provider, 1))]


def adopt_minute_cadence(db) -> None:
    """Boards that already list our roles were scheduled every 20 minutes to 2 hours.
    Pull any that sit further than a minute out onto the minute cadence. Quiet
    boards and never-checked imports keep their clocks, so a restart does not
    dump that backlog into the queue."""
    now = board_policy.utcnow()
    hiring = TrackedCompany.check_interval < int(QUIET_INTERVAL.total_seconds())
    db.execute(update(TrackedCompany).where(hiring).values(
        check_interval=int(MIN_INTERVAL.total_seconds())))
    db.execute(
        update(TrackedCompany)
        .where(hiring)
        .where(TrackedCompany.next_check_at.is_not(None))
        .where(TrackedCompany.next_check_at > now + MIN_INTERVAL)
        .values(next_check_at=now)
    )
    db.commit()
    db.expire_all()


async def harvester_loop():
    guard_stdio()
    with _db.SessionLocal() as db:
        seed_db_if_empty(db)
        track_f500(db)
        adopt_minute_cadence(db)
    await asyncio.gather(*(_worker_forever(provider) for provider in _lanes()))


def claim_background_lock():
    """Only one process may run the harvester/scout/retention loops on a DB.
    T29 found a second server on the same app.db running a stale harvester that
    undid provider moves and re-polled parked boards. An OS lock, not a row: the
    kernel drops it when its holder exits or crashes, so it never goes stale.
    Returns the open lock file (keep it open while the loops run) or None.
    ponytail: fcntl is POSIX-only (macOS/Linux, the dev and Docker targets)."""
    import fcntl
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(config.DATA_DIR / "background.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def cleanup_postings() -> int:
    with _db.SessionLocal() as db:
        removed = board_policy.prune_postings(db)
        db.commit()
    if removed:
        print(f"[board] expired {removed} postings outside the 14-day window")
    return removed


async def retention_loop():
    """Startup cleanup runs before serving; subsequent sweeps run every 15 min."""
    guard_stdio()
    while True:
        await asyncio.sleep(RETENTION_INTERVAL)
        try:
            cleanup_postings()
        except Exception:
            _log_exc()


_DISCOVERY_PATTERNS = {
    "greenhouse": re.compile(r"boards\.greenhouse\.io/([a-zA-Z0-9_.-]+)"),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/((?:[a-zA-Z0-9_.-]|%20)+)"),  # T44: "Flock%20Safety", not "flock"
    "lever": re.compile(r"jobs\.lever\.co/([a-zA-Z0-9_.-]+)"),
    # a job id must follow the company: the oneclick-ui/... paths are not companies
    "smartrecruiters": re.compile(r"jobs\.smartrecruiters\.com/([a-zA-Z0-9_-]+)/\d"),
    "workable": re.compile(r"apply\.workable\.com/([a-zA-Z0-9_-]+)/j/"),  # /j/: not its /api/ paths
}
_URL = re.compile(r"https?://[^\s\"'<>]+")

# SimplifyJobs' new-grad list: several commits a day (verified 2026-09-23), and
# exactly our band. It replaced awesome-easy-apply, frozen since May 2024 and the
# source of 317 of the 348 tracked boards that 404'd. Only `url` is read, from
# listings still `active`, to discover board slugs; nothing is republished (the
# repo declares no license).
SIMPLIFY_LISTINGS = ("https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions"
                     "/dev/.github/scripts/listings.json")

# Serper: Google honours site: reliably only on page 1 (T29, 10 live queries:
# page 2+ and the tbs time filter both fell back to YouTube/Reddit results), so
# reach comes from rotating the phrase daily, not from paging. Page 1 of the
# old fixed query found 0 untracked companies; a rotated phrase found 9.
SERPER_SITES = ("boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.ashbyhq.com", "jobs.lever.co",
                "myworkdayjobs.com", "apply.workable.com", "icims.com")
# One quoted phrase per day, so this stays a single Serper credit per site.
# Help desk and the other CS roles rotate in with the software phrases.
# No SERPER_API_KEY still means the scout is skipped.
SERPER_PHRASES = ("software engineer", "backend engineer", "new grad software engineer",
                  "machine learning engineer", "infrastructure engineer", "full stack engineer",
                  "data engineer", "business help desk", "IT support", "desktop support",
                  "cybersecurity analyst", "network engineer", "data analyst",
                  "systems administrator", "computer science new grad")
# Google Jobs through the official JSearch API (RapidAPI or OpenWeb Ninja).
# One query per interval, rotating the phrase: the Job Board refreshes every
# minute, and this must not burst the API on that cadence. No key skips the
# call. Results are postings, not a replacement for Greenhouse/Lever/Ashby/Workday.
JSEARCH_INTERVAL = timedelta(hours=4)
JSEARCH_QUERIES = (
    "Business Help Desk",
    "IT Help Desk",
    "IT Support",
    "Software Engineer",
    "Computer Science",
)
_JSEARCH_RAPIDAPI = "https://jsearch.p.rapidapi.com/search"
_JSEARCH_OPENWEB = "https://api.openwebninja.com/jsearch/search"
_JSEARCH_KEYS = ("JSEARCH_API_KEY", "OPENWEBNINJA_API_KEY", "RAPIDAPI_KEY")
SCOUT_CHECK = 60  # seconds between "is a scout due?" checks, aligned with the board refresh
# Serper stays on SCOUT_INTERVAL (a day, 7 credits a run) even though this loop
# wakes every minute. No SERPER_API_KEY means that scout is skipped, not faked.

# T31: the Internet Archive's CDX index lists every archived URL on the three
# ATS hosts - measured 2026-09-23: ~12,600 untracked boards across the three,
# free, no key. Weekly, one request per host; boards found this way start on a
# check spread over a day so a bulk import never starves boards already hiring.
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_HOSTS = ("jobs.ashbyhq.com", "job-boards.greenhouse.io", "boards.greenhouse.io", "jobs.lever.co")
WAYBACK_INTERVAL = timedelta(days=7)
WAYBACK_LIMIT = 500_000         # largest measured host (2026, 9 months) returned ~250k URLs
WAYBACK_SPREAD = timedelta(hours=24)


# Path segments on the ATS hosts that are not boards. Measured on the Wayback
# import (2026-09-23): 105 "root.<uuid>" slugs, 5 files/"api" and 51 slugs over
# 64 chars were checked and NONE was live. "embed" (boards.greenhouse.io/embed/
# job_app?token=...) carries a job id. Real boards reach 46 chars and may hold
# a dot ("arch.co", "kraken.com"), so neither is rejected by itself.
_NOT_A_BOARD = re.compile(
    r"^(api|embed|root\..*)$|\.(txt|xml|ico|json|js|css|png|jpg|svg|html|webmanifest)$")


# T44: Lever 404s a name in the wrong case both ways (palantir, CesiumAstro); 178
# boards in a year of Wayback answer only as written. Workable is case-sensitive
# too, but its accounts are all lowercase (a capitalised link redirects to /oops),
# so lowercasing repairs those links.
CASED = ("lever",)


def discover_slugs(text: str) -> list[tuple[str, str]]:
    """(provider, slug) pairs found in arbitrary text, already validated.

    The capture class permits dots, so a link like "boards.greenhouse.io/../x"
    yields the slug "..". Unfiltered, that is stored once and then fails every
    harvest cycle forever, counted as a vendor error. Reject it at the source.
    """
    found = []
    for provider, pattern in _DISCOVERY_PATTERNS.items():
        # lowercase BEFORE the set, or "Acme"/"acme"/"ACME" survive as three -
        # except where the case is the name (CASED)
        slugs = {s if provider in CASED else s.lower() for s in (unquote(m).strip() for m in pattern.findall(text))}
        found += [(provider, s) for s in sorted(slugs)
                  if _SLUG_OK.fullmatch(s) and len(s) <= 64 and not _NOT_A_BOARD.search(s)]
    return found


def _board_key(url: str) -> str:
    return url.lower().rstrip("/")  # Workday site names are case-insensitive (verified)


def _board_host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _board_owner(db, provider: str, boards: list[str]) -> TrackedCompany | None:
    """The company already harvesting boards on this host. The host, not the
    slug, is the company: a Workday tenant, an Oracle pod, an Eightfold host
    (the curated slug "appliedmaterials" is Workday tenant amat).
    ponytail: scans the provider's rows; hundreds today, index hosts if thousands."""
    wanted = {_board_host(b) for b in boards}
    return next((c for c in db.scalars(select(TrackedCompany).where(
        TrackedCompany.provider == provider, TrackedCompany.boards.is_not(None)))
        if wanted & {_board_host(b) for b in c.boards}), None)


def discover_boards(text: str) -> list[tuple[str, str, str]]:
    """(provider, slug, board URL) for the vendors a slug cannot locate (T36):
    Workday sites and Oracle career sites. Each adapter validates its own host,
    so nothing outside the vendor's domain can become a board to fetch."""
    found = {}
    for url in _URL.findall(text):
        for provider in ("workday", "oracle", "icims"):
            if hit := jd_adapters.by_name(provider).board_of(url):
                found.setdefault(_board_key(hit[1]), (provider, *hit))
    return list(found.values())


def track_company(db, provider: str, slug: str, source: str, first_check_at: datetime | None = None,
                  boards: list[str] | None = None, name: str | None = None) -> bool:
    """do_nothing, not do_update: the old version overwrote `provider` on every
    sighting, so a company listed under two ATSes flip-flopped and orphaned the
    postings harvested under the other one. A genuine ATS migration is handled
    by the harvester instead: a board that 404s is looked up on the other ATSes
    (T29 - 103 migrations had gone unnoticed). Returns True only when new."""
    if not _SLUG_OK.fullmatch(slug):
        raise ValueError(f"refusing suspicious board slug: {slug!r}")
    company = (_board_owner(db, provider, boards) if boards else None) or db.get(TrackedCompany, slug)
    if company is None:
        return db.execute(
            insert(TrackedCompany)
            .values(slug=slug, provider=provider, discovery_source=source, next_check_at=first_check_at,
                    boards=boards, name=name)
            .on_conflict_do_nothing(index_elements=["slug"])
        ).rowcount == 1
    # The move check can never find a board that needs more than a slug, so a
    # parked row under this slug is taken over here instead (T36) - unless it is
    # curated: a hand-verified company is never re-pointed by a discovered link.
    adopted = (company.provider != provider and company.gone_at is not None and provider not in MOVABLE
               and company.discovery_source != "fortune500")
    if adopted:
        print(f"[board] {slug} parked on {company.provider}, now tracked on {provider}")
        company.provider, company.boards, company.discovery_source = provider, None, source
    if company.provider == provider:
        have = {_board_key(b) for b in company.boards or []}
        extra = [b for b in boards or [] if _board_key(b) not in have]
        if extra:  # another of the company's sites, e.g. its new-grad one
            company.boards = [*(company.boards or []), *extra]
        company.name = company.name or name
    elif company.discovery_source == "fortune500":
        # A curated company's vendor was chosen and verified: PayPal is on Eightfold,
        # and its old Workday site lists the same jobs (279 vs 276) - never twice.
        print(f"[board] {provider} {boards[0] if boards else slug} skipped: {slug} is curated on {company.provider}")
    elif boards and not slug.endswith(f".{provider}"):
        # A live board of another vendor holds this slug: a same-named, different
        # company (all 5 seen: costar on Greenhouse is Co-Star, the Workday tenant
        # CoStar Group). Track this one apart; its host still dedupes it later.
        return track_company(db, provider, f"{slug}.{provider}", source, first_check_at, boards, name)
    if source == "pasted" or adopted:
        # The ATS API just answered for this link, so a board exists. Harvest
        # it on the next pass instead of waiting out the interval or a park.
        # Provider is NOT flipped for a slug-located vendor (T28): if the
        # recorded board 404s, the harvester's re-resolve finds this one.
        company.gone_at, company.last_synced_at, company.next_check_at = None, None, None
    return adopted


def track_f500(db) -> None:
    for provider, slug, name, boards in F500_BOARDS:
        track_company(db, provider, slug, "fortune500", boards=boards, name=name)
    db.commit()


async def _scout_github(client, db) -> int:
    """Companies with an active new-grad listing. Returns how many were new."""
    resp = await client.get(SIMPLIFY_LISTINGS)
    if resp.status_code != 200:
        print(f"[scout] {SIMPLIFY_LISTINGS} returned {resp.status_code}")
        return 0
    try:
        listings = resp.json()
    except ValueError as e:  # a bad upstream file is their problem, not a bug of ours
        print(f"[scout] listings.json is not JSON: {e}")
        return 0
    if not isinstance(listings, list):
        print("[scout] listings.json is not a list")
        return 0
    found = {}  # one entry per board: a company has many listings
    for item in listings:
        if not isinstance(item, dict) or item.get("active") is not True:
            continue
        url, name = str(item.get("url") or ""), item.get("company_name")
        name = name.strip() or None if isinstance(name, str) else None
        for provider, slug in discover_slugs(url):
            found.setdefault((provider, slug), (provider, slug, None, name))
        for provider, slug, board in discover_boards(url):
            found.setdefault(_board_key(board), (provider, slug, board, name))
    added = sum(track_company(db, provider, slug, "simplify", boards=board and [board], name=name)
                for provider, slug, board, name in found.values())
    db.commit()
    return added


async def _scout_serper(client, db) -> int:
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        print("[scout] no SERPER_API_KEY, skipping live discovery")
        return 0
    added = 0
    phrase = SERPER_PHRASES[datetime.now(timezone.utc).toordinal() % len(SERPER_PHRASES)]
    for site in SERPER_SITES:
        query = f'site:{site} "{phrase}"'
        try:
            resp = await client.post("https://google.serper.dev/search",
                                     json={"q": query}, headers={"X-API-KEY": key}, timeout=10)
            if resp.status_code != 200:
                print(f"[scout] serper returned {resp.status_code}")
                continue
            links = [str(item.get("link", "")) for item in resp.json().get("organic", [])]
            found = discover_slugs(" ".join(links))
            new = sum(track_company(db, provider, slug, "serper") for provider, slug in found)
            boards = discover_boards(" ".join(links))
            new += sum(track_company(db, provider, slug, "serper", boards=[board]) for provider, slug, board in boards)
            found += boards
            added += new
            # site: silently falling back to generic results shows up as 0 here
            print(f"[scout] serper {query}: {len(found)} boards in {len(links)} results, {new} new")
            db.commit()
        except httpx.HTTPError as e:      # vendor problem, expected noise
            db.rollback()
            print(f"[scout] serper unreachable: {e}")
    return added


def jsearch_query_at(moment: datetime) -> str:
    """The one phrase due at `moment`. Adjacent intervals rotate; a minute does not."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    slot = int(moment.timestamp() // JSEARCH_INTERVAL.total_seconds())
    return JSEARCH_QUERIES[slot % len(JSEARCH_QUERIES)]


def _jsearch_target() -> tuple[str, dict] | None:
    """(url, headers) for the official search API, or None when no key is set.

    The key stays in the header and is never logged. JSEARCH_API_URL /
    JSEARCH_API_HOST win when the project already points somewhere.
    """
    which = key = None
    for name in _JSEARCH_KEYS:
        value = os.environ.get(name)
        if value:
            which, key = name, value
            break
    if key is None:
        return None
    explicit = (os.environ.get("JSEARCH_API_URL") or "").strip()
    host_env = (os.environ.get("JSEARCH_API_HOST") or "").strip()
    if explicit:
        url = explicit
    elif which == "OPENWEBNINJA_API_KEY":
        url = _JSEARCH_OPENWEB
    else:
        host = host_env or "jsearch.p.rapidapi.com"
        if host.startswith("http"):
            url = host if host.rstrip("/").endswith("search") else host.rstrip("/") + "/search"
        else:
            url = f"https://{host}/search"
    hostname = (urlparse(url).hostname or "").lower()
    if "openwebninja.com" in hostname or (which == "OPENWEBNINJA_API_KEY" and not explicit and "rapidapi.com" not in hostname):
        return url, {"x-api-key": key}
    rapid_host = hostname or "jsearch.p.rapidapi.com"
    return url, {"X-RapidAPI-Key": key, "X-RapidAPI-Host": rapid_host}


def _http_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith("https://") or value.startswith("http://"):
        return value
    return None


def _jsearch_apply_url(job: dict) -> str | None:
    """Prefer job_apply_link, then a direct apply option, then any apply option, then Google."""
    if link := _http_url(job.get("job_apply_link")):
        return link
    direct = fallback = None
    options = job.get("apply_options")
    if isinstance(options, list):
        for opt in options:
            if not isinstance(opt, dict):
                continue
            link = _http_url(opt.get("apply_link"))
            if not link:
                continue
            if opt.get("is_direct") and direct is None:
                direct = link
            elif fallback is None:
                fallback = link
    return direct or fallback or _http_url(job.get("job_google_link"))


def _jsearch_country(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower().rstrip(".")
    if text in ("us", "usa", "u.s", "u.s.a", "united states", "united states of america"):
        return "US"
    if text in ("ca", "canada"):
        return "CA"
    raw = value.strip()
    if len(raw) == 2 and raw.isalpha():
        return raw.upper()
    return None


def _jsearch_location(job: dict) -> str | None:
    loc = job.get("job_location")
    if isinstance(loc, str) and loc.strip():
        text = loc.strip()
    else:
        parts = []
        for key in ("job_city", "job_state"):
            part = job.get(key)
            if isinstance(part, str) and part.strip():
                parts.append(part.strip())
        text = ", ".join(parts)
    remote = job.get("job_is_remote") is True
    if remote and text and "remote" not in text.lower():
        text = f"{text} · Remote"
    elif remote and not text:
        text = "Remote"
    return text or None


def _jsearch_employment(job: dict) -> set[str]:
    raw = []
    types = job.get("job_employment_types")
    if isinstance(types, list):
        raw.extend(types)
    elif isinstance(types, str):
        raw.append(types)
    one = job.get("job_employment_type")
    if isinstance(one, str):
        raw.append(one)
    found = set()
    for item in raw:
        token = re.sub(r"[^A-Za-z]", "", str(item)).upper()
        if "FULLTIME" in token:
            found.add("FULLTIME")
        if "PARTTIME" in token:
            found.add("PARTTIME")
        if "CONTRACT" in token:
            found.add("CONTRACTOR")
        if "INTERN" in token:
            found.add("INTERN")
    return found


def _plain_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r" *\n *", "\n", text).strip()


def _jsearch_description(job: dict) -> str | None:
    parts = []
    desc = job.get("job_description")
    if isinstance(desc, str) and desc.strip():
        parts.append(_plain_text(desc))
    highlights = job.get("job_highlights")
    if isinstance(highlights, dict):
        for label, lines in highlights.items():
            if not isinstance(lines, list):
                continue
            body = "\n".join(f"- {_plain_text(str(line))}" for line in lines if str(line).strip())
            if body:
                parts.append(f"{label}\n{body}")
    text = "\n\n".join(parts).strip()
    return text[:20000] or None


_RELATIVE_POSTED = re.compile(r"(\d+)\s*(minute|hour|day|week|month)s?\s*ago", re.I)


def _parse_posted_value(value, now: datetime) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        stamp = int(float(value))
        if stamp > 10**11:  # milliseconds; 2026 seconds are ~1.7e9
            stamp //= 1000
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    # Failures are None. UNDATED is reserved for "no date", never a guess of now.
    if (parsed := jd_adapters.parse_ats_date(text)) is not None:
        return parsed
    lowered = text.lower()
    if lowered in ("today", "just posted", "just now"):
        return now
    if lowered == "yesterday":
        return now - timedelta(days=1)
    match = _RELATIVE_POSTED.search(text)
    if not match:
        return None
    n = int(match.group(1))
    unit = match.group(2).lower()
    delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n),
             "day": timedelta(days=n), "week": timedelta(weeks=n),
             "month": timedelta(days=30 * n)}[unit]
    return now - delta


def _jsearch_posted(job: dict, now: datetime) -> datetime:
    """Exact datetime, then timestamp, then job_posted_at (ISO or '2 days ago')."""
    for key in ("job_posted_at_datetime_utc", "job_posted_at_timestamp", "job_posted_at"):
        if job.get(key) in (None, ""):
            continue
        parsed = _parse_posted_value(job[key], now)
        if parsed is not None:
            return parsed
    return UNDATED


def jsearch_records(payload) -> list[dict]:
    """Search responses use data[]; a bare list or one job object is accepted too."""
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            items = data
        elif isinstance(payload.get("job_title"), str) or payload.get("job_id") or payload.get("job_uid"):
            items = [payload]
        else:
            items = []
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def map_jsearch_job(job: dict, now: datetime | None = None) -> dict | None:
    """JSearch JSON onto the posting fields we store. None when title, company, or apply URL is missing."""
    title = job.get("job_title")
    company = job.get("employer_name")
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(company, str) or not company.strip():
        return None
    url = _jsearch_apply_url(job)
    if not url:
        return None
    raw_id = job.get("job_id") or job.get("job_uid")
    job_id = str(raw_id).strip() if raw_id else None
    return {
        "title": title.strip(),
        "company": company.strip(),
        "location": _jsearch_location(job),
        "country": _jsearch_country(job.get("job_country")),
        "url": url,
        "description": _jsearch_description(job),
        "employment": _jsearch_employment(job),
        "published_at": _jsearch_posted(job, now or board_policy.utcnow()),
        "job_id": job_id or None,
    }


def _jsearch_slug(name: str) -> str | None:
    """A company slug that cannot collide with an ATS slug, so a harvest cannot close these rows."""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    token = re.sub(r"[^A-Za-z0-9]+", "-", folded).strip("-").lower()
    if not token:
        return None
    slug = ("jsearch-" + token)[:64].strip("-")
    if not slug.startswith("jsearch-") or not _SLUG_OK.fullmatch(slug):
        return None
    return slug


def _is_jsearch_company(slug: str | None) -> bool:
    return bool(slug and slug.startswith("jsearch-"))


def _ensure_jsearch_company(db, name: str) -> str | None:
    slug = _jsearch_slug(name)
    if slug is None:
        return None
    track_company(db, "jsearch", slug, "jsearch", name=name)
    company = db.get(TrackedCompany, slug)
    if company is None or company.provider != "jsearch":
        return None
    company.name = name
    if company.check_interval is None:
        company.check_interval = int(QUIET_INTERVAL.total_seconds())
        company.next_check_at = board_policy.utcnow() + QUIET_INTERVAL
    return slug


def _keep_jsearch(mapped: dict, now: datetime) -> bool:
    """Full-time US/Canada roles we already harvest. Intern *titles* stay stored; the feed hides them."""
    if not is_target_role(mapped["title"]):
        return False
    if not is_target_location(mapped["location"], mapped.get("country")):
        return False
    employment = mapped["employment"]
    if employment and "FULLTIME" not in employment:
        return False
    return board_policy.is_recent(mapped["published_at"], now)


def _save_jsearch_posting(db, mapped: dict, now: datetime) -> str:
    """Insert or refresh one posting. Never rewrites a Greenhouse/Lever/Ashby/Workday row."""
    slug = _ensure_jsearch_company(db, mapped["company"])
    if slug is None:
        return "skipped"
    url = mapped["url"]
    ext = mapped.get("job_id") or None
    by_url = db.get(JobPosting, url)
    by_id = db.scalar(select(JobPosting).where(JobPosting.external_id == ext)) if ext else None
    if by_url is not None and not _is_jsearch_company(by_url.company_slug):
        return "skipped"
    if by_id is not None and not _is_jsearch_company(by_id.company_slug):
        by_id = None
    if by_id is not None and by_url is not None and by_id.url != by_url.url:
        db.delete(by_id)
        db.flush()
        by_id = None
    row = by_url or by_id
    fields = {
        "title": mapped["title"],
        "location": mapped["location"],
        "status": "open",
        "created_at": mapped["published_at"],
        "updated_at": now,
        "external_id": ext,
        "description": mapped["description"],
        "company_slug": slug,
    }
    if row is None:
        db.add(JobPosting(url=url, first_seen_at=now, **fields))
        return "new"
    if row.url != url:
        first = row.first_seen_at or now
        db.delete(row)
        db.flush()
        db.add(JobPosting(url=url, first_seen_at=first, **fields))
        return "updated"
    for key, value in fields.items():
        setattr(row, key, value)
    return "updated"


def _store_jsearch_records(db, records: list[dict]) -> int:
    now = board_policy.utcnow()
    new = 0
    for record in records:
        mapped = map_jsearch_job(record, now)
        if mapped is None or not _keep_jsearch(mapped, now):
            continue
        if _save_jsearch_posting(db, mapped, now) == "new":
            new += 1
    db.commit()
    return new


async def _scout_jsearch(client, db) -> int:
    """One full-time US query against the official JSearch API. No key, no call."""
    target = _jsearch_target()
    if target is None:
        print("[scout] no JSEARCH_API_KEY, RAPIDAPI_KEY, or OPENWEBNINJA_API_KEY, skipping Google Jobs")
        return 0
    url, headers = target
    query = jsearch_query_at(datetime.now(timezone.utc))
    params = {
        "query": query,
        "country": "us",
        "employment_types": "FULLTIME",
        "date_posted": "month",
        "page": "1",
        "num_pages": "1",
    }
    try:
        resp = await client.get(url, params=params, headers=headers, timeout=15)
    except httpx.HTTPError as e:
        print(f"[scout] jsearch unreachable: {type(e).__name__}")
        return 0
    if resp.status_code != 200:
        print(f"[scout] jsearch returned {resp.status_code}")
        return 0
    try:
        payload = resp.json()
    except ValueError:
        print("[scout] jsearch response is not JSON")
        return 0
    records = jsearch_records(payload)
    new = _store_jsearch_records(db, records)
    print(f"[scout] jsearch {query!r}: {len(records)} jobs, {new} new")
    return new


async def _scout_wayback(client, db) -> int:
    """Board slugs from a year of archived URLs. Returns how many were new."""
    since = (board_policy.utcnow() - timedelta(days=365)).strftime("%Y%m%d")
    added = 0
    for host in WAYBACK_HOSTS:
        try:
            resp = await client.get(WAYBACK_CDX, timeout=300, params={
                "url": host + "/", "matchType": "prefix", "from": since, "fl": "original",
                "collapse": "urlkey", "limit": WAYBACK_LIMIT})
        except httpx.HTTPError as e:
            print(f"[scout] wayback {host}: {type(e).__name__}: {e}")
            continue
        if resp.status_code != 200:  # 429 included: the Archive blocks those who push on
            print(f"[scout] wayback {host} returned {resp.status_code}; skipping until next week")
            continue
        urls = resp.text.split()
        if len(urls) >= WAYBACK_LIMIT:
            print(f"[scout] wayback {host}: hit the {WAYBACK_LIMIT} URL limit, some boards missed")
        now = board_policy.utcnow()
        new = sum(track_company(db, provider, slug, "wayback",
                                now + random.random() * WAYBACK_SPREAD)
                  for provider, slug in discover_slugs(" ".join(urls)))
        db.commit()
        added += new
        print(f"[scout] wayback {host}: {len(urls)} URLs, {new} new boards")
    return added


def _scout_due(marker: str, interval: timedelta) -> bool:
    """Measured across restarts. Every --reload restart used to rerun the scout:
    downloads and Serper credits each time. A marker is touched only after a
    successful run, so a failed one is retried within SCOUT_CHECK - except a
    paid one, which counts as done once started (T45)."""
    try:
        return time.time() - (config.DATA_DIR / marker).stat().st_mtime >= interval.total_seconds()
    except FileNotFoundError:
        return True


async def _scout(marker: str, interval: timedelta, *sources, paid: bool = False) -> None:
    if not _scout_due(marker, interval):
        return
    if paid:  # a run failing after its paid queries would retry every SCOUT_CHECK (42 credits an hour)
        (config.DATA_DIR / marker).touch()
    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
            with _db.SessionLocal() as db:
                added = 0
                for source in sources:
                    added += await source(client, db)
                total = db.execute(select(func.count()).select_from(TrackedCompany)).scalar()
                print(f"[scout] {marker} done: {added} new companies, tracking {total}")
        (config.DATA_DIR / marker).touch()
    except Exception:
        # Same rule as the harvester: a bug in our own code must be loud, not a
        # one-line warning indistinguishable from a network hiccup.
        _log_exc()


_jsearch_skip_logged = False


async def scout_loop():
    guard_stdio()
    # A missing key must not touch jsearch_last_run. That marker is the paid
    # interval; burning it on a skip would hide a key added later for hours.
    global _jsearch_skip_logged
    while True:
        await _scout("simplify_last_run", SIMPLIFY_INTERVAL, _scout_github)
        await _scout("scout_last_run", SCOUT_INTERVAL, _scout_serper, paid=True)  # marker kept: same daily timing
        # One JSearch query per multi-hour slot, not a burst on the minute refresh.
        if _jsearch_target() is not None:
            await _scout("jsearch_last_run", JSEARCH_INTERVAL, _scout_jsearch, paid=True)
        elif not _jsearch_skip_logged:
            print("[scout] no JSEARCH_API_KEY, RAPIDAPI_KEY, or OPENWEBNINJA_API_KEY, skipping Google Jobs")
            _jsearch_skip_logged = True
        await _scout("wayback_last_run", WAYBACK_INTERVAL, _scout_wayback)
        await asyncio.sleep(SCOUT_CHECK)
