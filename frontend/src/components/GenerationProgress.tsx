import React, { useEffect, useState } from 'react';
import { Sparkles, AlertCircle, RotateCcw } from 'lucide-react';

/**
 * Live progress for a long-running job.
 *
 * A cold image generation on the free tier takes about 45 seconds, and the
 * critique (a vision pass plus a large LLM document on a local CPU model) takes
 * longer still. A bare spinner over that span is indistinguishable from a hung
 * app, so this shows the current stage, a running clock, and a paced bar.
 *
 * The bar is explicitly an *estimate* — the providers expose no real progress —
 * so it eases toward 92% over the expected duration and only completes when the
 * job actually does. It never silently sits at 100% while work continues.
 */

export interface GenerationProgressProps {
  stage: string;
  /** Seconds the job has been running, from the server's own clock. */
  elapsedSeconds: number;
  /** Typical duration, used to pace the estimate bar. */
  expectedSeconds?: number;
  label?: string;
  /** Slow-but-normal note shown once the job outruns its estimate. */
  patienceNote?: string;
}

function formatElapsed(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 60) return `${whole}s`;
  return `${Math.floor(whole / 60)}m ${String(whole % 60).padStart(2, '0')}s`;
}

/** Eases toward — but never reaches — 92%, so completion is always the job's call. */
function estimateProgress(elapsed: number, expected: number): number {
  return 92 * (1 - Math.exp((-2.2 * elapsed) / Math.max(expected, 1)));
}

export const GenerationProgress: React.FC<GenerationProgressProps> = ({
  stage,
  elapsedSeconds,
  expectedSeconds = 45,
  label = 'Creating your artwork',
  patienceNote = 'The free image service queues requests at busy times — this is still running.',
}) => {
  // The server's elapsed value only refreshes each poll; tick locally in
  // between so the clock moves smoothly instead of jumping every second or two.
  const [localElapsed, setLocalElapsed] = useState(elapsedSeconds);

  useEffect(() => setLocalElapsed(elapsedSeconds), [elapsedSeconds]);

  useEffect(() => {
    const id = setInterval(() => setLocalElapsed((prev) => prev + 0.25), 250);
    return () => clearInterval(id);
  }, []);

  const pct = estimateProgress(localElapsed, expectedSeconds);
  const overrunning = localElapsed > expectedSeconds * 1.6;

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-6 animate-fade-up">
      <div className="flex items-center gap-4">
        <div className="relative flex-shrink-0">
          <div className="absolute inset-0 rounded-2xl bg-amber-500/25 blur-xl animate-float-slow" />
          <div className="relative w-11 h-11 rounded-2xl bg-gradient-to-tr from-amber-500 to-rose-500 flex items-center justify-center shadow-lg shadow-amber-500/25">
            <Sparkles className="w-5 h-5 text-slate-950" />
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <p className="font-semibold text-slate-100 truncate">{label}</p>
            <span
              className="text-xs tabular-nums text-slate-500 flex-shrink-0"
              aria-hidden="true"
            >
              {formatElapsed(localElapsed)}
            </span>
          </div>
          <p className="text-sm text-slate-400 mt-0.5 truncate">{stage}…</p>
        </div>
      </div>

      <div
        className="mt-5 h-1.5 w-full rounded-full bg-slate-800 overflow-hidden"
        role="progressbar"
        aria-label={`${label}: ${stage}`}
        aria-busy="true"
        // Genuinely indeterminate — the bar is a pacing estimate, so don't
        // report a fabricated percentage to assistive tech.
        aria-valuetext={`${stage}, ${formatElapsed(localElapsed)} elapsed`}
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-amber-500 to-rose-500 transition-[width] duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>

      {overrunning && (
        <p className="mt-3 text-xs text-slate-500 leading-relaxed">{patienceNote}</p>
      )}
    </div>
  );
};

/** Square shimmer standing in for artwork that hasn't arrived yet. */
export const ArtworkSkeleton: React.FC<{ label?: string }> = ({ label }) => (
  <div className="flex flex-col gap-3">
    {label && (
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">{label}</p>
    )}
    <div className="aspect-square rounded-2xl bg-slate-800/60 border border-slate-700/50 shimmer" />
    <div className="space-y-2">
      <div className="h-4 w-2/5 rounded bg-slate-800 shimmer" />
      <div className="h-3 w-3/5 rounded bg-slate-800/70 shimmer" />
    </div>
  </div>
);

export const JobErrorPanel: React.FC<{
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
}> = ({ message, onRetry, retryLabel = 'Try again' }) => (
  <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-5 flex items-start gap-3">
    <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
    <div className="min-w-0 flex-1">
      <p className="text-sm text-rose-200 leading-relaxed">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-amber-400 hover:text-amber-300 transition"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          {retryLabel}
        </button>
      )}
    </div>
  </div>
);
