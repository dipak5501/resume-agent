import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useSearchParams } from 'react-router-dom'

import { AppShell } from './AppShell'
import { Onboarding } from './components/Onboarding'
import { Answers } from './pages/Answers'
import { Board } from './pages/Board'
import { Compose } from './pages/Compose'
import { History } from './pages/History'
import { Library } from './pages/Library'
import { Profile } from './pages/Profile'
import { Tailor } from './pages/Tailor'
import { Track } from './pages/Track'

// Dev-only component gallery. The `import.meta.env.DEV ? … : null` is a compile-time
// constant, so the whole branch (and the Gallery chunk) is dead-code-eliminated
// from the prod build — never in the bundle, never in the nav.
const Gallery = import.meta.env.DEV ? lazy(() => import('./pages/dev/Gallery')) : null

// Home = the first-run checklist above the Compose brief. While setup is
// incomplete this is a taller, naturally-scrolling orientation page; once it's
// done the checklist goes and Compose is a viewport-locked working screen (T21).
// Preserves the pre-router reload-resume link: an old ?job=… lands you back on
// that run's /tailor route.
// The four-pillar Guarantees band that used to sit here was removed in T27 —
// recover it from git history if the landing page ever wants it back.
function Home() {
  const [params] = useSearchParams()
  const legacy = params.get('job')
  if (legacy) return <Navigate to={`/tailor/${legacy}`} replace />
  return (
    <>
      <Onboarding />
      <Compose key={`${params.get('from') ?? ''}:${params.get('url') ?? ''}`} />
    </>
  )
}

export default function App() {
  return (
    <Routes>
      {/* Outside the shell so an old /dashboard link lands on the tracker
          without crossfading through an empty page. */}
      <Route path="/dashboard" element={<Navigate to="/track" replace />} />
      <Route element={<AppShell />}>
        <Route path="/" element={<Home />} />
        <Route path="/board" element={<Board />} />
        <Route path="/tailor/:jobId" element={<Tailor />} />
        <Route path="/library" element={<Library />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/answers" element={<Answers />} />
        <Route path="/history" element={<History />} />
        <Route path="/track" element={<Track />} />
        {Gallery && (
          <Route
            path="/dev/gallery"
            element={
              <Suspense fallback={null}>
                <Gallery />
              </Suspense>
            }
          />
        )}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
