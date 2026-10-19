// Canonical field vocabulary (T12). Mirrors the backend `canonical.py` (Phase 2)
// — the shared contract for what a form field *means*, decoupled from its label.
export type Canonical =
  | 'full_name'
  | 'first_name'
  | 'last_name'
  | 'email'
  | 'phone'
  | 'location'
  | 'address' // T19: granular address subfield (street/postal/state/country) — detected but NEVER filled (profile has only a coarse location)
  | 'linkedin'
  | 'github'
  | 'portfolio'
  | 'website'
  | 'work_authorization'
  | 'years_experience'
  | 'resume_upload'
  | 'cover_letter'
  | 'free_text'
  | 'unknown'

// Structure-only descriptor of one form field. This is ALL that ever leaves the
// browser (Phase 2 /autofill/map) — never the user's filled values or page HTML.
export interface Descriptor {
  field_ref: number // index into the detected field list; stable within one detect()
  tag: string // input | select | textarea
  type: string // text | email | tel | file | ...
  name: string
  id: string
  autocomplete: string
  aria_label: string
  placeholder: string
  label: string // resolved associated <label> text
  data_automation_id: string // Workday's primary field signal (e.g. legalNameSection_firstName)
  required: boolean
  // T19: structure-only nearby signal (enclosing heading/legend text) for the
  // LLM mapping lane — never a value. Optional; the deterministic heuristic
  // ignores it, so mapper.ts/field_map.py parity is unaffected.
  context?: string
}

export interface Mapping {
  field_ref: number
  canonical: Canonical
  confidence: number // 0..1
  source: 'heuristic' | 'cache' | 'llm'
}

export interface Profile {
  name?: string | null
  email?: string | null
  phone?: string | null
  location?: string | null
  work_auth?: string | null
  // T17 — assisted screening self-ID (all voluntary; "yes"/"no" for the booleans)
  work_eligible?: string | null
  needs_sponsorship?: string | null
  gender?: string | null
  race?: string | null
  disability?: string | null
  veteran?: string | null
  links?: { github?: string | null; linkedin?: string | null; portfolio?: string | null }
  auto_apply?: boolean | null
}

export interface JobSummary {
  id: string
  title: string
  status: string
  created_at: string
  has_pdf: boolean
}

// What the executor should do with a field + how the popup reports it.
// 'answer' = a free-text screening question routed to the backend answerer (T13).
export type FillAction = 'fill' | 'attach' | 'blank' | 'flag' | 'answer'

export interface PlanItem {
  field_ref: number
  label: string
  canonical: Canonical
  action: FillAction
  value?: string
  reason?: string
  // T13: set on answered free-text fields so the popup can badge AI drafts and
  // offer "save to bank".
  needsReview?: boolean
  source?: AnswerResult['source']
  // T17: a radio/select choice we selected (not free text) — rendered as a
  // non-editable "review this selection" mark, never the draft text editor.
  control?: 'choice'
}

// One screening answer from POST /autofill/answer (T13). Empty `answer` ⇒
// nothing to fill (blank + flag); `needs_review` ⇒ AI draft, show the badge.
export interface AnswerResult {
  answer: string
  source: 'bank_verbatim' | 'bank_adapted' | 'llm_fresh' | 'blank'
  needs_review: boolean
  canonical?: string | null
  reason?: string | null
}

export interface FillResult {
  filled: PlanItem[]
  attached: PlanItem[]
  blank: PlanItem[]
  flagged: PlanItem[]
  unknownRequired?: string[]
  error?: string
}

// The tailored PDF, base64'd so it survives chrome message serialization
// (structured clone of Blob/ArrayBuffer is not available across sendMessage).
export interface PdfPayload {
  base64: string
  filename: string
}
