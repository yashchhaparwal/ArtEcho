import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom';
import {
  ArrowLeft, Download, RefreshCw, Loader2, Sparkles, Palette,
  CheckCircle2, AlertCircle, ChevronDown, ChevronUp, BookOpen
} from 'lucide-react';
import { sessionsApi, pollJob } from '../services/api';
import type {
  SessionResultResponse, GeneratedArtworkResponse, CritiqueResponse, Artwork,
} from '../services/api';
import { useAuth } from '../context/AuthContext';
import { GenerationProgress, ArtworkSkeleton, JobErrorPanel } from '../components/GenerationProgress';

import { resolveAssetUrl } from '../config';

// Measured against the free Pollinations tier: a cold generation sits around
// 45s. The critique is slower — a vision pass plus a large single-shot document
// from a local CPU model. Both only pace the progress bar.
const EXPECTED_GENERATION_SECONDS = 45;
const EXPECTED_CRITIQUE_SECONDS = 90;

const resolveUrl = resolveAssetUrl;

interface JobProgress {
  stage: string;
  elapsed: number;
}

// ── Sub-components ────────────────────────────────────────────────────────────

const CritiqueField: React.FC<{ label: string; value?: string }> = ({ label, value }) => {
  if (!value) return null;
  return (
    <div className="mb-4">
      <h4 className="text-xs font-semibold uppercase tracking-widest text-amber-400 mb-1.5">{label}</h4>
      <p className="text-sm text-slate-300 leading-relaxed">{value}</p>
    </div>
  );
};

const TagList: React.FC<{ label: string; items?: string[]; variant?: 'green' | 'rose' }> = ({
  label, items = [], variant = 'green'
}) => {
  if (!items.length) return null;
  const color = variant === 'green'
    ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
    : 'bg-rose-500/10 text-rose-300 border-rose-500/20';
  return (
    <div className="mb-4">
      <h4 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-2">{label}</h4>
      <div className="flex flex-wrap gap-2">
        {items.map((s, i) => (
          <span key={i} className={`px-2.5 py-1 rounded-lg border text-xs ${color}`}>{s}</span>
        ))}
      </div>
    </div>
  );
};

const ArtworkCritiquePanel: React.FC<{
  label: string;
  section?: {
    composition?: string;
    color_theory?: string;
    symbolism?: string;
    emotional_impact?: string;
    strengths?: string[];
    weaknesses?: string[];
  };
}> = ({ label, section }) => {
  const [open, setOpen] = useState(true);
  if (!section) return null;
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden animate-fade-up">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-slate-800/50 transition"
      >
        <div className="flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-semibold text-slate-200">{label}</span>
        </div>
        {open ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
      </button>
      {open && (
        <div className="px-5 pb-5 border-t border-slate-800">
          <div className="pt-4">
            <CritiqueField label="Composition" value={section.composition} />
            <CritiqueField label="Colour Theory" value={section.color_theory} />
            <CritiqueField label="Symbolism" value={section.symbolism} />
            <CritiqueField label="Emotional Impact" value={section.emotional_impact} />
            <TagList label="Strengths" items={section.strengths} variant="green" />
            <TagList label="Weaknesses" items={section.weaknesses} variant="rose" />
          </div>
        </div>
      )}
    </div>
  );
};

const ArtworkPanel: React.FC<{
  label: string;
  imageUrl: string;
  title: string;
  subtitle?: string;
}> = ({ label, imageUrl, title, subtitle }) => {
  const [imgError, setImgError] = useState(false);
  const [loaded, setLoaded] = useState(false);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">{label}</p>
      <div className="relative aspect-square rounded-2xl overflow-hidden bg-slate-800 border border-slate-700/60">
        {/* The generated file is served fresh off disk; hold a shimmer until the
            bitmap actually decodes so the panel never flashes an empty box. */}
        {!loaded && !imgError && <div className="absolute inset-0 shimmer bg-slate-800/60" />}
        {!imgError ? (
          <img
            src={resolveUrl(imageUrl)}
            alt={title}
            loading="lazy"
            onLoad={() => setLoaded(true)}
            className={`w-full h-full object-cover transition-opacity duration-500 ${loaded ? 'opacity-100' : 'opacity-0'}`}
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Palette className="w-12 h-12 text-slate-600" />
          </div>
        )}
      </div>
      <div>
        <p className="font-semibold text-slate-100">{title}</p>
        {subtitle && <p className="text-sm text-slate-500">{subtitle}</p>}
      </div>
    </div>
  );
};

const ReferencePanel: React.FC<{ references: Artwork[] }> = ({ references }) => {
  if (references.length === 1) {
    const ref = references[0];
    return (
      <ArtworkPanel
        label="Reference Artwork"
        imageUrl={ref.image_url}
        title={ref.title}
        subtitle={`${ref.artist}${ref.year ? ` · ${ref.year}` : ''}`}
      />
    );
  }
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3">
        {references.length} Reference Artworks
      </h3>
      <div className="grid grid-cols-2 gap-3">
        {references.map((ref) => (
          <div key={ref.id} className="rounded-xl overflow-hidden bg-slate-900 border border-slate-800">
            <div className="aspect-[4/3] bg-slate-800">
              <img
                src={resolveUrl(ref.image_url)}
                alt={ref.title}
                loading="lazy"
                className="w-full h-full object-cover"
              />
            </div>
            <div className="p-3">
              <p className="text-xs font-semibold text-slate-200 truncate">{ref.title}</p>
              <p className="text-xs text-slate-500 truncate">{ref.artist}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ── Main Result Page ──────────────────────────────────────────────────────────

export const ResultPage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();

  // Set when arriving straight from the chat page's Generate button.
  const incomingJobId = (location.state as { jobId?: string } | null)?.jobId ?? null;

  const [result, setResult] = useState<SessionResultResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);
  const [critique, setCritique] = useState<CritiqueResponse | null>(null);
  const [error, setError] = useState('');
  const [critiqueError, setCritiqueError] = useState('');

  const [genProgress, setGenProgress] = useState<JobProgress | null>(null);
  const [critiqueProgress, setCritiqueProgress] = useState<JobProgress | null>(null);

  // Stop polling if the user navigates away mid-job. The job itself keeps
  // running server-side, so coming back simply picks up the finished artwork.
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);

  // Guards against the auto-critique effect firing twice for one artwork.
  const critiqueStartedFor = useRef<string | null>(null);

  const loadResult = useCallback(async () => {
    if (!sessionId) return null;
    try {
      const res = await sessionsApi.getResult(sessionId);
      setResult(res.data);
      if (res.data.latest_generated?.critique) {
        setCritique(res.data.latest_generated.critique);
      }
      return res.data;
    } catch {
      setError('Failed to load results. Please try again.');
      return null;
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  // ── critique ───────────────────────────────────────────────────────────────

  const runCritique = useCallback(async () => {
    if (!sessionId) return;
    setCritiqueError('');
    setCritiqueProgress({ stage: 'Looking at your artwork', elapsed: 0 });

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const started = await sessionsApi.startCritique(sessionId);

      // Already critiqued — the server answers immediately, no job to follow.
      if (started.data.status === 'done' && started.data.result) {
        setCritique(started.data.result);
        return;
      }
      if (!started.data.job_id) throw new Error('No critique job was returned.');

      const critiqueResult = await pollJob<CritiqueResponse>(sessionId, started.data.job_id, {
        signal: controller.signal,
        onProgress: (job) =>
          setCritiqueProgress({ stage: job.stage, elapsed: job.elapsed_seconds }),
      });
      setCritique(critiqueResult);
    } catch (err: any) {
      if (err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return;
      setCritiqueError(
        err?.response?.data?.detail || err?.message || 'Critique generation failed.'
      );
    } finally {
      setCritiqueProgress(null);
    }
  }, [sessionId]);

  // ── generation ─────────────────────────────────────────────────────────────

  /** Follow a generation job that is already queued server-side. */
  const followGeneration = useCallback(
    async (jobId: string) => {
      if (!sessionId) return;
      setError('');
      setGenProgress({ stage: 'Composing your prompt', elapsed: 0 });

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await pollJob<GeneratedArtworkResponse>(sessionId, jobId, {
          signal: controller.signal,
          onProgress: (job) => setGenProgress({ stage: job.stage, elapsed: job.elapsed_seconds }),
        });
        setCritique(null);
        critiqueStartedFor.current = null;
        await loadResult();
      } catch (err: any) {
        if (err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return;
        setError(err?.response?.data?.detail || err?.message || 'Image generation failed.');
      } finally {
        setGenProgress(null);
      }
    },
    [sessionId, loadResult]
  );

  /**
   * Start a generation and follow it.
   *
   * The endpoint is idempotent per session: if a job is already in flight —
   * after a mid-generation refresh, say — this attaches to it rather than
   * queueing a second 45-second call.
   */
  const startGeneration = useCallback(async () => {
    if (!sessionId || genProgress) return;
    setError('');
    setGenProgress({ stage: 'Composing your prompt', elapsed: 0 });
    try {
      const started = await sessionsApi.startGeneration(sessionId, true);
      if (!started.data.job_id) throw new Error('No generation job was returned.');
      await followGeneration(started.data.job_id);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Image generation failed.');
      setGenProgress(null);
    }
  }, [sessionId, genProgress, followGeneration]);

  // ── lifecycle ──────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!user) { navigate('/login'); return; }
    loadResult().then((data) => {
      // Arrived straight from the Generate button — pick the job up mid-flight.
      if (incomingJobId && !data?.latest_generated) {
        // Clear the router state so a refresh doesn't re-follow a stale job.
        navigate(location.pathname, { replace: true, state: null });
        followGeneration(incomingJobId);
      }
    });
    // Deliberately runs once per session: re-running on every render would
    // restart polling. Later refreshes go through loadResult directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, sessionId]);

  // Critique the newest artwork automatically, once it exists and isn't busy.
  useEffect(() => {
    const latest = result?.latest_generated;
    if (!latest || latest.critique || critique) return;
    if (genProgress || critiqueProgress) return;
    if (critiqueStartedFor.current === latest.id) return;
    critiqueStartedFor.current = latest.id;
    runCritique();
  }, [result, critique, genProgress, critiqueProgress, runCritique]);

  const handleRegenerate = async () => {
    if (genProgress) return;
    setCritique(null);
    critiqueStartedFor.current = null;
    await startGeneration();
  };

  const handleSave = async () => {
    if (!sessionId || isSaving) return;
    setIsSaving(true);
    try {
      await sessionsApi.saveSession(sessionId);
      setSavedOk(true);
    } catch {
      setError('Failed to save artwork to gallery. Please try again.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDownload = () => {
    const url = result?.latest_generated?.image_url;
    if (!url) return;
    const a = document.createElement('a');
    a.href = resolveUrl(url);
    a.download = `muse-generated-${Date.now()}.png`;
    a.target = '_blank';
    a.click();
  };

  // ── render ─────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <div className="h-8 w-64 rounded-lg bg-slate-800 shimmer mb-8" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <ArtworkSkeleton label="Reference Artwork" />
          <ArtworkSkeleton label="Generated Artwork" />
        </div>
      </div>
    );
  }

  if (error && !result) {
    return (
      <div className="max-w-xl mx-auto px-4 py-16 text-center space-y-4">
        <AlertCircle className="w-10 h-10 text-rose-400 mx-auto" />
        <p className="text-rose-400">{error}</p>
        <Link to="/library" className="text-amber-400 hover:underline text-sm">Back to Library</Link>
      </div>
    );
  }

  const latest: GeneratedArtworkResponse | null = result?.latest_generated ?? null;
  const allReferences = (result?.reference_artworks ?? []) as Artwork[];
  const primaryRef = allReferences[0];
  const allGenerations = result?.generated_artworks ?? [];
  const isGenerating = genProgress !== null;

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-8">
        <button
          onClick={() => navigate(`/session/${sessionId}`)}
          aria-label="Back to conversation"
          className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-100 hover:border-slate-700 transition"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="min-w-0">
          <h1 className="text-2xl font-extrabold text-slate-100 tracking-tight truncate">
            {result?.session_title ?? 'Your Artwork Results'}
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {allGenerations.length} generation{allGenerations.length !== 1 ? 's' : ''}
            {latest?.model_provider ? ` · ${latest.model_provider}` : ''}
          </p>
        </div>
      </div>

      {/* Generation error */}
      {error && result && (
        <div className="mb-6">
          <JobErrorPanel message={error} onRetry={handleRegenerate} retryLabel="Try regenerating" />
        </div>
      )}

      {/* Live generation progress */}
      {isGenerating && (
        <div className="mb-6">
          <GenerationProgress
            stage={genProgress.stage}
            elapsedSeconds={genProgress.elapsed}
            expectedSeconds={EXPECTED_GENERATION_SECONDS}
            label={latest ? 'Creating a new artwork' : 'Creating your artwork'}
          />
        </div>
      )}

      {/* Side-by-side artworks. A session can blend several references, so all
          of them are shown rather than only the first. */}
      {primaryRef && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-10">
          <ReferencePanel references={allReferences} />

          {isGenerating && !latest ? (
            <ArtworkSkeleton label="Generated Artwork" />
          ) : latest ? (
            <ArtworkPanel
              label={`Generated Artwork #${latest.generation_index}`}
              imageUrl={latest.image_url}
              title="Your Muse Creation"
              subtitle={
                allReferences.length > 1
                  ? `Blended from ${allReferences.length} references`
                  : `Inspired by ${primaryRef.title}`
              }
            />
          ) : (
            <div className="flex flex-col justify-center items-center gap-4 rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 p-8 text-center">
              <Sparkles className="w-8 h-8 text-slate-600" />
              <p className="text-sm text-slate-400">No artwork has been generated for this session yet.</p>
              <button
                onClick={startGeneration}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-rose-500 text-slate-950 font-semibold text-sm shadow-lg shadow-amber-500/20 hover:from-amber-400 hover:to-rose-400 transition"
              >
                Generate artwork
              </button>
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      {latest && (
        <div className="flex flex-wrap gap-3 mb-10">
          <button
            onClick={handleRegenerate}
            disabled={isGenerating}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-200 hover:text-white hover:border-slate-600 transition disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
          >
            {isGenerating
              ? <><Loader2 className="w-4 h-4 animate-spin" />Regenerating…</>
              : <><RefreshCw className="w-4 h-4" />Regenerate</>
            }
          </button>
          <button
            onClick={handleDownload}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-200 hover:text-white hover:border-slate-600 transition text-sm font-medium"
          >
            <Download className="w-4 h-4" />
            Download
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving || savedOk}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition disabled:opacity-50 ${
              savedOk
                ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300'
                : 'bg-gradient-to-r from-amber-500 to-rose-500 text-slate-950 shadow-lg shadow-amber-500/20 hover:from-amber-400 hover:to-rose-400'
            }`}
          >
            {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : savedOk ? <CheckCircle2 className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
            {savedOk ? 'Saved to Gallery!' : isSaving ? 'Saving…' : 'Save to Gallery'}
          </button>
        </div>
      )}

      {/* Critiques */}
      {(latest || critique) && (
        <div className="space-y-4">
          <h2 className="text-lg font-bold text-slate-100">Artwork Critique</h2>

          {critiqueProgress && (
            <GenerationProgress
              stage={critiqueProgress.stage}
              elapsedSeconds={critiqueProgress.elapsed}
              expectedSeconds={EXPECTED_CRITIQUE_SECONDS}
              label="Muse is analysing both artworks"
              patienceNote="The critique runs on your local model and is the slowest step — it's still working."
            />
          )}

          {critiqueError && (
            <JobErrorPanel message={critiqueError} onRetry={runCritique} retryLabel="Retry critique" />
          )}

          {critique && (
            <>
              <ArtworkCritiquePanel label="Reference Artwork Critique" section={critique.reference_critique ?? undefined} />
              <ArtworkCritiquePanel label="Generated Artwork Critique" section={critique.generated_critique ?? undefined} />

              {critique.comparison && (
                <div className="p-5 bg-gradient-to-br from-amber-500/5 to-rose-500/5 border border-amber-500/20 rounded-2xl animate-fade-up">
                  <h4 className="text-xs font-semibold uppercase tracking-widest text-amber-400 mb-3">Comparative Analysis</h4>
                  <p className="text-sm text-slate-300 leading-relaxed">{critique.comparison}</p>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Prompt used */}
      {latest?.prompt_synthesized && (
        <details className="mt-8 group">
          <summary className="cursor-pointer text-xs text-slate-600 hover:text-slate-400 transition select-none">
            View generation prompt ▾
          </summary>
          <p className="mt-2 text-xs text-slate-500 bg-slate-900 border border-slate-800 rounded-xl p-4 leading-relaxed font-mono">
            {latest.prompt_synthesized}
          </p>
        </details>
      )}
    </div>
  );
};
