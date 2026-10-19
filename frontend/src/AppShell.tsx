import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { NavLink, useLocation, useOutlet } from "react-router-dom";

import { useExtensionStatus } from "@/hooks/useExtension";
import { pageFade } from "@/lib/motion";

// The desk organizer's index tabs (T14). Two zones — "do" (Tailor, Board) and
// "set up & track" (the application list, then Library, Profile, Answers,
// History). "Set up & track" used to be a mute caption; it is the tracker page.
// NavLink sets aria-current="page", which the .idx-tab styles turn into the
// pulled-forward cream tab with a marigold ink-mark.
const TABS = [
  { to: "/", letter: "A", label: "Tailor", zone: "do", end: true },
  { to: "/board", letter: "B", label: "Board", zone: "do" },
  { to: "/track", letter: "C", label: "Set up & track", zone: "set up & track" },
  { to: "/library", letter: "D", label: "Library", zone: "set up & track" },
  { to: "/profile", letter: "E", label: "Profile", zone: "set up & track" },
  { to: "/answers", letter: "F", label: "Answers", zone: "set up & track" },
  { to: "/history", letter: "G", label: "History", zone: "set up & track" },
] as const;

function ZoneCaption({ children }: { children: React.ReactNode }) {
  return (
    <span
      aria-hidden
      className="hidden shrink-0 self-end pb-2 pl-1 font-mono text-[9px] tracking-[0.26em] text-cream-soft/55 uppercase sm:inline"
    >
      {children}
    </span>
  );
}

function ExtensionPill() {
  const { installed, active } = useExtensionStatus();
  const label = active ? "extension active" : installed ? "extension, backend down" : "extension not loaded";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10px] tracking-[0.18em] uppercase ${
        active
          ? "border-marigold/40 text-marigold"
          : "border-cream-soft/25 text-cream-soft"
      }`}
      title={
        active
          ? "The extension is loaded and reached the backend"
          : installed
            ? "The extension is loaded but did not reach the backend"
            : "The extension is not loaded"
      }
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full ${active ? "bg-marigold" : "bg-cream-soft/50"}`}
      />
      {label}
    </span>
  );
}

function ExtensionBanner() {
  const status = useExtensionStatus();
  if (status.active) return null;
  return (
    <div className="border-b border-desk-line px-6 py-3">
      <div className="mx-auto max-w-[96rem]">
        <p className="font-mono text-[11px] leading-relaxed tracking-[0.04em] text-cream-soft">
          {status.installed
            ? "Extension loaded, but it cannot reach the app at 127.0.0.1:8000. Start the backend, then reload this page."
            : "Extension not loaded. This page cannot install a Chrome extension for you."}
        </p>
        {!status.installed && (
          <ol className="mt-2 list-decimal space-y-0.5 pl-4 font-mono text-[11px] leading-relaxed text-cream-soft">
            <li>Open chrome://extensions</li>
            <li>Turn on Developer mode</li>
            <li>Choose Load unpacked and select the extension/dist folder</li>
            <li>Reload this page. The pill turns active once the extension reaches the backend.</li>
          </ol>
        )}
      </div>
    </div>
  );
}

export function AppShell() {
  // Route transition: a quick crossfade between pages, keyed on the path. The
  // Run→Result reveal lives in Tailor (same path, so this doesn't fire there).
  // Reduced motion: render the outlet plainly (instant swap) — the crossfade
  // relies on an opacity animation that motion leaves stuck at 0 when reduced.
  const location = useLocation();
  const outlet = useOutlet();
  const reduced = useReducedMotion();
  return (
    // A flex column, not a document: the header takes what it needs and <main>
    // is the one scroll region. That hands routes a *definite* height to fill
    // (Compose's viewport-lock, T21) without hardcoding the header's pixel
    // height, which wraps responsively and would drift.
    <div className="flex h-svh flex-col overflow-x-clip">
      <header className="relative shrink-0">
        <div className="mx-auto max-w-[96rem] px-6">
          <div className="flex items-center justify-between border-t border-desk-line pt-3">
            <span className="font-mono text-[10px] tracking-[0.32em] text-cream-soft uppercase">
              Est. on the desk
            </span>
            <ExtensionPill />
          </div>

          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 pt-2 pb-3">
            <NavLink
              to="/"
              className="font-serif text-2xl font-medium tracking-tight text-cream"
            >
              Résumé<span className="text-marigold">·</span>Proof
            </NavLink>
          </div>

          {/* the index-tab rail — the tabs stand on the marigold desk edge below */}
          <nav
            aria-label="Sections"
            className="tab-rail -mb-px flex items-end gap-1 overflow-x-auto"
          >
            <ZoneCaption>do</ZoneCaption>
            {TABS.filter((t) => t.zone === "do").map((t) => (
              <Tab key={t.to} {...t} />
            ))}
            <span
              aria-hidden
              className="mx-1 h-6 w-px shrink-0 self-end bg-desk-line"
            />
            {TABS.filter((t) => t.zone === "set up & track").map((t) => (
              <Tab key={t.to} {...t} />
            ))}
          </nav>
        </div>
        <div className="h-[3px] bg-marigold" />
        <div className="h-px bg-desk-line" />
        <ExtensionBanner />
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">
        {reduced ? (
          outlet
        ) : (
          // initial={false}: no entrance on first load (content is immediate on a
          // cold/direct-URL load) — only client-side navigations crossfade.
          // h-full keeps the percentage chain intact so a route can fill <main>;
          // taller routes simply overflow it and scroll.
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={location.pathname}
              variants={pageFade}
              initial="hidden"
              animate="show"
              exit="exit"
              className="h-full"
            >
              {outlet}
            </motion.div>
          </AnimatePresence>
        )}
      </main>
    </div>
  );
}

function Tab({
  to,
  letter,
  label,
  end,
}: {
  to: string;
  letter: string;
  label: string;
  end?: boolean;
}) {
  return (
    <NavLink to={to} end={end} className="idx-tab">
      <span className="idx-kicker">{letter}</span>
      <span className="idx-label">{label}</span>
    </NavLink>
  );
}
