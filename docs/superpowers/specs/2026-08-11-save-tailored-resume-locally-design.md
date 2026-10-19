# Save tailored résumé locally + application tracker (local-dev only)

- **Status:** approved (brainstormed) · **local-dev only** — intentionally does nothing useful on a real server deploy.
- **Scope:** one new backend endpoint + one new frontend button + a `.gitignore` line. The existing "Download PDF" button is **unchanged**.

## Goal

From the Result page, let the user **file a tailored résumé into the repo** for local tracking:
copy the already-rendered PDF into `tailored-resume/<company>/[<position>/]<name>_resume.pdf`
and record the application in a CSV. This is a working-locally convenience, not a product feature.

## Why a backend endpoint (not a browser download)

The browser sandbox can only write to the user's Downloads folder, never to an arbitrary path like
`<repo>/tailored-resume/`. But the backend runs locally **inside this repo**, so a small endpoint copies
the PDF (it already exists server-side at `job.result.pdf_path`) to the repo folder. On a real server this
would write on the server's disk — meaningless — so the feature is explicitly local-only. Accepted.

## UX

Two buttons on Result:

- **Download PDF** — *unchanged*: browser download only. No repo write, no CSV.
- **Save locally** — *new, small secondary button*: repo write + CSV upsert. Shows a short confirmation
  of where it saved (e.g. "Saved → tailored-resume/adobe/kashif_resume.pdf"), or an inline error.

## Company + position

One LLM call (`llm.chat`, JSON format) reads the job's stored JD text and returns `{company, position}`.
No dialog — automatic on click. Both are **slugified path-safe** before use.

- Slug: lowercase → non-alphanumeric runs collapse to `-` → strip leading/trailing `-` → cap length (~60).
- Empty/failed extraction → `unknown-company` / `unknown-position` (never blank, never a path separator).
- Path-traversal guard: the resolved target path MUST stay inside `tailored-resume/`; reject otherwise.

## Folder rule (option C — flat first, then nest; idempotent on re-save)

```
if (company, position) already has a tracker row → target = its recorded resume_path   # overwrite in place
else:
    flat   = tailored-resume/<company>/<name>_resume.pdf
    nested = tailored-resume/<company>/<position>/<name>_resume.pdf
    target = nested if (flat exists OR nested exists) else flat
write PDF → target   # overwrite if present; mkdir -p parents
```

- First save for a company → **flat**.
- A later, *different* position → **nested** by position.
- **Re-saving the same role** (same JD → same company+position; e.g. after a revision round) →
  **overwrites in place** at wherever it first landed (flat or nested), leaving no duplicate/orphan.
  The tracker CSV is the memory of where the role lives.

## Filename

`<name>_resume.pdf` where `<name>` = profile name slugified (`Kashif Manzer` → `kashif-manzer_resume.pdf`).
Falls back to `resume.pdf` when the profile has no name.

## CSV tracker — `tailored-resume/applications-tracker.csv`

One row **per (company, position)**, upserted on each Save locally.

| column | filled by | notes |
|---|---|---|
| `date_applied` | auto | date of (latest) save, ISO `YYYY-MM-DD` |
| `company` | auto | slug |
| `position` | auto | slug |
| `resume_path` | auto | repo-root-relative, e.g. `tailored-resume/adobe/kashif-manzer_resume.pdf` |
| `ats_score` | auto | `result.report.ats_after.overall` |
| `apply_url` | auto | `job.apply_url` (blank for pasted JDs) |
| `status` | **user** | blank on create; preserved on re-save |
| `notes` | **user** | blank on create; preserved on re-save |

Upsert = read (if file exists) → match row by (`company`,`position`) → update the auto columns, **preserve**
`status`/`notes` → else append. Header written when the file is created. Uses Python's stdlib `csv`.

## Backend

- `POST /jobs/{job_id}/save-local` → `{ saved_path, company, position }` on success; 404 if the job/PDF
  isn't found, 4xx/5xx surfaced as an honest message.
- New `app/services/local_save.py`: slugify, resolve target path (with traversal guard), copy PDF, CSV upsert.
  Base dir = `config.TAILORED_RESUME_DIR` (default `<repo-root>/tailored-resume`, env-overridable so tests
  point it at a tmp dir).
- Company/position extraction: small helper reusing `llm.chat`; reads the job store record's JD text.

## Frontend

- `saveLocal(jobId)` in `lib/api.ts` → `POST /jobs/:id/save-local`.
- `useSaveLocal` mutation hook.
- Result page: a small "Save locally" button beside the existing download row; shows the returned path or
  the error inline. No change to "Download PDF".

## Git

Add `/tailored-resume/` to the repo `.gitignore`. Nothing under it is ever committed or pushed.

## Out of scope

- Any change to the Download PDF button.
- Server/deploy behavior (feature is local-only by design).
- CSV columns beyond the eight above; manual status workflow beyond a free-text column.

## Testing (ponytail minimum)

Backend test against a tmp `TAILORED_RESUME_DIR`, LLM extraction mocked:
- path rule: 1st save → flat; 2nd (different position) → nested; re-save nested → overwrites (no new file).
- CSV upsert: new row appended; re-save updates auto columns but **preserves** `status`/`notes`.
- slug path-safety: a malicious "company"/"position" (e.g. `../../etc`) cannot escape `tailored-resume/`.
