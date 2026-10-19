import type { Canonical, Descriptor, Mapping } from '../shared/types'

const HIGH = 0.95 // native signal (autocomplete / input type / file)
const KEYWORD = 0.85 // label/name keyword match

// autocomplete tokens → canonical (the cheapest, most reliable signal)
const AUTOCOMPLETE: Record<string, Canonical> = {
  name: 'full_name',
  'given-name': 'first_name',
  'family-name': 'last_name',
  email: 'email',
  tel: 'phone',
  'tel-national': 'phone',
}

// Ordered most-specific → most-general; 'full_name' is last because bare "name"
// is broad (it appears inside "company name" etc.).
const LABEL_RULES: { canonical: Canonical; re: RegExp }[] = [
  { canonical: 'first_name', re: /\b(first[\s_-]*name|given[\s_-]*name|forename|f[\s_-]?name)\b/ },
  { canonical: 'last_name', re: /\b(last[\s_-]*name|family[\s_-]*name|surname|l[\s_-]?name)\b/ },
  { canonical: 'email', re: /\be[\s_-]?mail\b/ },
  { canonical: 'phone', re: /\b(phone|mobile|cell|telephone|tel)\b/ },
  { canonical: 'linkedin', re: /linked[\s_-]?in/ },
  { canonical: 'github', re: /git[\s_-]?hub/ },
  { canonical: 'portfolio', re: /portfolio/ },
  { canonical: 'website', re: /\b(website|personal site|blog|homepage|url)\b/ },
  {
    canonical: 'work_authorization',
    re: /(work[\s_-]*authoriz|authoriz(ed|ation)\s*to\s*work|right\s*to\s*work|sponsor|visa|work permit|legally.*work)/,
  },
  {
    canonical: 'years_experience',
    re: /(years?[\s_-]*of[\s_-]*experience|years?[\s_-]*experience|experience.*years|total experience)/,
  },
  { canonical: 'cover_letter', re: /cover[\s_-]*letter/ },
  { canonical: 'location', re: /\b(city|location|where.*located|current location|based in)\b/ },
  // T19: granular address subfields — detected but NEVER filled (profile has only a coarse location),
  // so a "Postal Code"/"Address Line"/"State"/"Country" field can't inherit the city value.
  { canonical: 'address', re: /\b(street|address|postal|post\s*code|zip|state|province|county|country)\b/ },
  { canonical: 'full_name', re: /\b(full[\s_-]*name|your[\s_-]*name|legal[\s_-]*name|applicant[\s_-]*name|candidate[\s_-]*name)\b/ },
]

// Workday keys fields off data-automation-id (camelCase/underscore compounds
// like `legalNameSection_firstName`), often the ONLY reliable signal. Word-
// boundary label rules miss those, so match the normalized id by substring.
// Order matters: firstName/lastName before a bare 'name' would, address before city.
const AUTOMATION_ID: [string, Canonical][] = [
  ['firstname', 'first_name'],
  ['lastname', 'last_name'],
  ['legalnamesectionname', 'full_name'],
  ['email', 'email'],
  ['phone', 'phone'],
  ['linkedin', 'linkedin'],
  ['github', 'github'],
  ['city', 'location'],
  ['coverletter', 'cover_letter'],
]

/** Deterministic, free, in-browser field classifier. Returns a canonical key +
 *  confidence; 'unknown' (low confidence) is the Phase-2 LLM lane's input. */
export function mapDescriptor(d: Descriptor): { canonical: Canonical; confidence: number } {
  const tag = d.tag.toLowerCase()
  const type = d.type.toLowerCase()
  const hay = [d.name, d.id, d.aria_label, d.placeholder, d.label, d.data_automation_id].join(' ').toLowerCase()
  const aid = d.data_automation_id.toLowerCase().replace(/[^a-z]/g, '') // normalize camelCase/underscores

  if (type === 'file') {
    if (/cover/.test(hay)) return { canonical: 'cover_letter', confidence: HIGH }
    // Only attach the résumé to a field that actually reads as the résumé slot.
    // Two other file inputs must NOT get it: Ashby's anonymous "autofill from
    // résumé" dropzone (no id/name/keyword → would trigger the site's parser),
    // and a named-but-generic custom "Upload file" question (Lever `cards[…]`).
    // Résumé fields essentially always carry a resume/cv/file-upload tell.
    if (/resume|résumé|\bcv\b|curriculum|file-upload/.test(hay))
      return { canonical: 'resume_upload', confidence: HIGH }
    return { canonical: 'unknown', confidence: 0.2 }
  }

  // Workday lane: a strong, deterministic signal — check before generic rules.
  if (aid) {
    for (const [needle, canonical] of AUTOMATION_ID) {
      if (aid.includes(needle)) return { canonical, confidence: HIGH }
    }
  }

  const ac = d.autocomplete.toLowerCase().trim()
  if (AUTOCOMPLETE[ac]) return { canonical: AUTOCOMPLETE[ac], confidence: HIGH }
  if (type === 'email') return { canonical: 'email', confidence: HIGH }
  if (type === 'tel') return { canonical: 'phone', confidence: HIGH }
  // A field whose whole label is just "name" (Ashby, many ATSes) is the
  // applicant's name — "company name"/"first name" carry a qualifier.
  const label = d.label.trim().toLowerCase()
  if (d.name.toLowerCase() === 'name' || label === 'name') return { canonical: 'full_name', confidence: HIGH }

  for (const { canonical, re } of LABEL_RULES) {
    if (re.test(hay)) return { canonical, confidence: KEYWORD }
  }
  if (tag === 'textarea') return { canonical: 'free_text', confidence: 0.6 }
  return { canonical: 'unknown', confidence: 0.2 }
}

export function mapAll(ds: Descriptor[]): Mapping[] {
  return ds.map((d) => ({ field_ref: d.field_ref, source: 'heuristic' as const, ...mapDescriptor(d) }))
}
