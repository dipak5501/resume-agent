# Resume Agent — Assisted Autofill (T12)

MV3 Chrome extension that fills an ATS application form from your profile and
attaches your JD-tailored résumé. **Fill stops for you to review.** Auto-apply
submits one run only after you turn the switch on in the app, and it stops
when a required field is unknown or the page has a CAPTCHA, login wall, or
paywall. Runs in your own browser/session (real IP, real credentials).

## Architecture

```
① website + backend (brain)      ② this extension (hands + bridge)     ③ ATS site
   profile, résumé library,          content script (detect/fill),        Greenhouse / Lever
   tailoring pipeline, LLM,          background worker (talks to ①),
   mapping cache (/autofill/map)     popup (pick run, Fill, review)
```

① and ③ never talk directly. The **background worker** is the only actor that
calls the backend (it has `host_permissions`, so its fetches bypass page CORS).

## Field mapping — 3-tier hybrid

1. **Fast lane** (`content/mapper.ts`): deterministic synonym/attribute matcher
   resolves the stable ~80% in-browser, free. Nothing leaves the page.
2. **LLM lane** (`POST /autofill/map`): only the fields the matcher marks
   `unknown` are sent — **structure only** (labels/attributes/types), never your
   values or page HTML — and mapped in **one LLM call per form**.
3. **Cache** (`field_mappings` table): the resolved map is keyed by
   `host + form_sig` and promoted, so the next hit on that form is instant/free.

`content/plan.ts` is the trust boundary: value always comes from the profile,
no profile value → blank, low confidence → blank + flagged, `free_text` → left
for you.

## Develop

```bash
pnpm install
pnpm build        # → dist/  (load this unpacked)
pnpm test         # detector / mapper / plan / apply / no-submit  (vitest + jsdom)
pnpm typecheck
pnpm dev          # HMR dev build
```

## Load in Chrome

1. Start the backend on `127.0.0.1:8000` and run at least one tailoring job so
   the popup has a run to pick (`GET /jobs`). Set `OLLAMA_API_KEY` if you want
   the LLM lane for unknown fields (the heuristic + cache need no key).
2. `pnpm build`.
3. Chrome → `chrome://extensions` → enable **Developer mode** → **Load unpacked**
   → select `extension/dist`. Reload the app at `http://127.0.0.1:5173`. The
   header pill says **extension active** once the extension reaches `/health`.
4. Open a **Greenhouse** or **Lever** application page (reload it once if it was
   already open before installing), click the toolbar icon, pick a tailored run,
   and hit **Fill**. Review every field, then submit yourself.

## Scope (T12)

Greenhouse, Lever, Ashby + Workday (the host list is a semi-open registry).
**Workday is convention-based** (adapts to its `data-automation-id` fields) and
not yet verified against a live form — its apply pages sit behind account
creation; verify/tune against a real Workday posting. Free-text/screening
answers are detected and left for you; drafting them + the answer bank is
stone 3 (T13). Auto-apply submits one armed run only; Fill never does.
