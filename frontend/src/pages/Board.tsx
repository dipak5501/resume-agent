import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/states/EmptyState";
import { InlineError } from "@/components/states/InlineError";
import { ListSkeleton } from "@/components/states/ListSkeleton";
import { SectionHeading } from "@/components/ui/SectionHeading";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/button";
import { getBoardFeed } from "@/lib/api";
import { rise, stagger, useEntrance } from "@/lib/motion";
import type { JobPostingOut } from "@/lib/types";
import { MAX_AGE_MS, postingTime } from "@/lib/utils";

// The open Job Board refetches on its own. Full-time stays selected unless
// Include internships is on; that flag is part of the query.
const BOARD_REFRESH_MS = 60_000

// A date-only vendor (Workday, Oracle, Amazon) gives a day; the time would be ours.
function formatDate(iso: string, dateOnly: boolean): string {
  return new Date(postingTime(iso)).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    ...(dateOnly ? {} : { hour: "numeric", minute: "2-digit" }),
  });
}

function getPageNumbers(current: number, total: number) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  if (current <= 4) return [1, 2, 3, 4, 5, "...", total];
  if (current >= total - 3)
    return [1, "...", total - 4, total - 3, total - 2, total - 1, total];
  return [1, "...", current - 1, current, current + 1, "...", total];
}

export function Board() {
  const [page, setPage] = useState(1);
  const [includeInterns, setIncludeInterns] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const resultsRef = useRef<HTMLDivElement>(null);
  const scrollAfterLoad = useRef(false);

  const { data, dataUpdatedAt, isPending, isError, refetch, isPlaceholderData, isFetching } = useQuery({
    queryKey: ["board", page, includeInterns],
    queryFn: () => getBoardFeed(page, includeInterns),
    placeholderData: keepPreviousData,
    refetchInterval: BOARD_REFRESH_MS,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
  });

  // Expire cached rows on time even during an outage. Focus/refetch also catches
  // timers that the browser throttled while this tab was in the background.
  useEffect(() => {
    const nextExpiry = Math.min(...(data?.jobs ?? [])
      .map((j) => postingTime(j.created_at) + MAX_AGE_MS)
      .filter((expires) => expires > Date.now()));
    const updateClock = () => setNow(Date.now());
    const timer = window.setTimeout(updateClock,
      Math.min(BOARD_REFRESH_MS, Math.max(1, nextExpiry - Date.now())));
    window.addEventListener('focus', updateClock);
    document.addEventListener('visibilitychange', updateClock);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('focus', updateClock);
      document.removeEventListener('visibilitychange', updateClock);
    };
  }, [data, now]);

  useEffect(() => {
    if (!data || isPlaceholderData || isFetching || isError) return;
    const lastPage = Math.max(1, data.total_pages);
    if (page > lastPage) {
      scrollAfterLoad.current = true;
      // The server's page count can shrink after expiration/closure.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPage(lastPage);
      return;
    }
    if (scrollAfterLoad.current) {
      const results = resultsRef.current;
      const scroller = results?.closest('main');
      if (results && scroller) {
        scroller.scrollTo({ top: scroller.scrollTop + results.getBoundingClientRect().top
          - scroller.getBoundingClientRect().top - 16, behavior: 'instant' });
      }
      scrollAfterLoad.current = false;
    }
  }, [data, page, isPlaceholderData, isFetching, isError]);

  function changePage(next: number) {
    if (next === page || isFetching || isPlaceholderData) return;
    scrollAfterLoad.current = true;
    setPage(next);
  }

  function setEmployment(next: boolean) {
    if (next === includeInterns || isFetching || isPlaceholderData) return;
    scrollAfterLoad.current = true;
    setIncludeInterns(next);
    setPage(1);
  }

  const visibleJobs = data?.jobs.filter((job) => {
    const posted = postingTime(job.created_at);
    const current = Math.max(now, dataUpdatedAt);
    return posted > current - MAX_AGE_MS && posted <= current;
  }) ?? [];

  const entrance = useEntrance();

  return (
    <motion.div
      variants={stagger}
      {...entrance}
      className="mx-auto max-w-[96rem] space-y-8 px-6 py-16 lg:py-20"
    >
      <motion.div variants={rise}>
        <SectionHeading
          kicker="do · job board"
          title={
            <>
              Job Board<span className="text-marigold">.</span>
            </>
          }
        >
          {includeInterns
            ? "Software, data, systems, IT, security, networking, and business help desk roles posted in the last 14 days, including internships."
            : "Full-time software, data, systems, IT, security, networking, and business help desk roles posted in the last 14 days."}
          {" "}Newest first, from tracked companies.
        </SectionHeading>
        <div role="group" aria-label="Employment type" className="mt-5 flex flex-wrap gap-2">
          {([
            [false, "Full-time"],
            [true, "Include internships"],
          ] as const).map(([on, label]) => (
            <button
              key={label}
              type="button"
              aria-pressed={includeInterns === on}
              disabled={isFetching || isPlaceholderData}
              onClick={() => setEmployment(on)}
              className={`rounded-md border px-4 py-2 font-mono text-[12px] tracking-[0.1em] uppercase transition disabled:opacity-40 ${
                includeInterns === on
                  ? "border-marigold bg-marigold text-ink"
                  : "border-desk-line bg-transparent text-cream-soft hover:bg-paper-edge/10 hover:text-cream"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </motion.div>

      <motion.div ref={resultsRef} variants={rise} aria-busy={isFetching}>
        {isPending && <ListSkeleton />}
        {isError && (
          <InlineError onRetry={() => refetch()}>
            Couldn&rsquo;t refresh the Board. Please try again.
          </InlineError>
        )}

        {data && visibleJobs.length === 0 && (
          <EmptyState title="No recent roles on this page.">
            Listings leave the Board 14 days after posting. New roles appear as
            companies are checked. Try refreshing or choosing another page.
            <button type="button" onClick={() => void refetch()} disabled={isFetching}
              className="mt-3 block font-mono text-xs underline underline-offset-4 disabled:opacity-40">
              Refresh Board
            </button>
          </EmptyState>
        )}

        {data && (
          <>
            {visibleJobs.length > 0 && <Sheet
              as="ul"
              sm
              className="divide-y divide-border overflow-hidden"
            >
              {visibleJobs.map((j) => (
                <Row key={j.url} job={j} />
              ))}
            </Sheet>}

            {data.total_pages > 0 && <div aria-label="Board pagination" className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-desk-line pt-6">
              <Button
                onClick={() => changePage(Math.max(page - 1, 1))}
                disabled={page === 1 || isFetching || isPlaceholderData}
                className="rounded-md border border-desk-line bg-transparent px-5 py-2 font-mono text-[12px] tracking-[0.1em] text-cream-soft uppercase transition hover:bg-paper-edge/10 hover:text-cream disabled:opacity-30"
              >
                ← Prev
              </Button>
              <div className="order-last flex w-full items-center justify-center gap-1.5 sm:order-none sm:w-auto">
                {getPageNumbers(page, data.total_pages).map((p, i) => (
                  <button
                    key={i}
                    disabled={p === "..." || isFetching || isPlaceholderData}
                    aria-current={p === page ? 'page' : undefined}
                    aria-label={typeof p === 'number' ? `Page ${p}` : undefined}
                    onClick={() => typeof p === "number" && changePage(p)}
                    className={`flex h-8 min-w-[32px] items-center justify-center rounded px-2 font-mono text-[12px] transition ${
                      p === page
                        ? "bg-marigold text-ink"
                        : p === "..."
                          ? "cursor-default text-cream-soft/40"
                          : "text-cream-soft hover:bg-paper-edge/10 hover:text-cream"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <Button
                onClick={() => changePage(page + 1)}
                disabled={isFetching || isPlaceholderData || !data.has_more}
                className="rounded-md border border-desk-line bg-transparent px-5 py-2 font-mono text-[12px] tracking-[0.1em] text-cream-soft uppercase transition hover:bg-paper-edge/10 hover:text-cream disabled:opacity-30"
              >
                Next →
              </Button>
            </div>}
          </>
        )}
      </motion.div>
    </motion.div>
  );
}

function CompanyLogo({ slug, name }: { slug: string; name: string }) {
  const [error, setError] = useState(false);
  const initial = name.charAt(0).toUpperCase();

  if (error) {
    return (
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-ink font-serif text-2xl font-medium text-cream shadow-sm sm:h-24 sm:w-24 sm:text-[40px]">
        {initial}
      </span>
    );
  }

  return (
    <img
      src={`https://t1.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://${slug}.com&size=128`}
      alt={`${name} logo`}
      className="h-12 w-12 shrink-0 rounded-xl object-contain p-2 bg-white shadow-sm ring-1 ring-ink/5 sm:h-24 sm:w-24 sm:p-3"
      onError={() => setError(true)}
      onLoad={(event) => {
        const image = event.currentTarget;
        if (image.naturalWidth <= 16 || image.naturalHeight <= 16) setError(true);
      }}
    />
  );
}

function Row({ job }: { job: JobPostingOut }) {
  const navigate = useNavigate();
  return (
    <li className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-4 px-4 py-5 transition hover:bg-paper-edge sm:flex sm:gap-6 sm:px-6">
      <CompanyLogo slug={job.company_slug} name={job.company_name ?? job.company_slug} />
      <div className="min-w-0 flex-1 space-y-1">
        <span className="block truncate font-mono text-sm text-ink font-bold tracking-tight uppercase sm:text-lg">
          {job.company_name ?? job.company_slug}
        </span>
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          className="block font-mono text-base text-ink/80 hover:underline hover:text-marigold transition-colors sm:truncate sm:text-[20px]"
        >
          {job.title}
        </a>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-0.5">
          {/* no location is not "Remote": show nothing rather than guess */}
          {job.location && (
            <>
              <span className="font-mono text-[13px] tracking-wide text-ink font-medium">
                {job.location}
              </span>
              <span className="font-mono text-[13px] tracking-wide text-ink/40">
                •
              </span>
            </>
          )}
          <span className="font-mono text-[13px] tracking-wide text-ink/70">
            posted {formatDate(job.created_at, job.date_only)}
          </span>
          {/* one item, so a wrap never strands the bullet from its label */}
          {job.openings > 1 && (
            <span className="font-mono text-[13px] tracking-wide text-ink/70">
              <span className="mr-3 text-ink/40">•</span>
              {job.openings} openings
            </span>
          )}
        </div>
      </div>
      <Button
        onClick={() => navigate(`/?from=board&url=${encodeURIComponent(job.url)}`)}
        className="col-start-2 justify-self-start shrink-0 rounded-md border border-marigold/50 bg-marigold/15 px-5 py-2.5 font-mono text-[13px] tracking-[0.1em] text-accent-ink uppercase transition hover:bg-marigold hover:text-ink hover:border-marigold"
      >
        Tailor & Apply
      </Button>
    </li>
  );
}
