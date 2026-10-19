// Dev-only backend origin. Multi-user auth (token) lands with T-multiuser; for
// now the extension talks to a localhost backend with a single 'default' profile.
export const BACKEND_URL = 'http://127.0.0.1:8000'

// A field is only auto-filled at/above this mapping confidence. Below it, the
// field is left BLANK and flagged — a blank is recoverable, wrong data on a
// submitted application is not (T12 trust boundary).
export const FILL_THRESHOLD = 0.7
