import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  ArrowLeft, Download, RefreshCw, Loader2, Sparkles, Palette,
  CheckCircle2, AlertCircle, ChevronDown, ChevronUp, BookOpen
} from 'lucide-react';
import { sessionsApi } from '../services/api';
import type { SessionResultResponse, GeneratedArtworkResponse, CritiqueResponse } from '../services/api';
import { useAuth } from '../context/AuthContext';

const BACKEND = 'http://localhost:8000';

function resolveUrl(url: string): string {
  if (!url) return '';
  return url.startsWith('/') ? `${BACKEND}${url}` : url;
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
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
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
  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">{label}</p>
      <div className="aspect-square rounded-2xl overflow-hidden bg-slate-800 border border-slate-700/60">
        {!imgError ? (
          <img
            src={resolveUrl(imageUrl)}
            alt={title}
            className="w-full h-full object-cover"
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

// ── Main Result Page ──────────────────────────────────────────────────────────

export const ResultPage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [result, setResult] = useState<SessionResultResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);
  const [critiqueLoading, setCritiqueLoading] = useState(false);
  const [critique, setCritique] = useState<CritiqueResponse | null>(null);
  const [error, setError] = useState('');
  const [critiqueError, setCritiqueError] = useState('');

  const loadResult = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await sessionsApi.getResult(sessionId);
      setResult(res.data);
      // Check if latest already has a critique
      if (res.data.latest_generated?.critique) {
        setCritique(res.data.latest_generated.critique);
      }
    } catch {
      setError('Failed to load results. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  const triggerCritique = useCallback(async () => {
    if (!sessionId || critique || critiqueLoading) return;
    setCritiqueLoading(true);
    setCritiqueError('');
    try {
      const res = await sessionsApi.generateCritique(sessionId);
      setCritique(res.data);
    } catch (err: any) {
      setCritiqueError(err.response?.data?.detail || 'Critique generation failed.');
    } finally {
      setCritiqueLoading(false);
    }
  }, [sessionId, critique, critiqueLoading]);

  useEffect(() => {
    if (!user) { navigate('/login'); return; }
    loadResult();
  }, [user, loadResult, navigate]);

  // Auto-trigger critique once result loads (non-blocking)
  useEffect(() => {
    if (result?.latest_generated && !result.latest_generated.critique && !critique) {
      triggerCritique();
    }
  }, [result, critique, triggerCritique]);

  const handleRegenerate = async () => {
    if (!sessionId || isRegenerating) return;
    setIsRegenerating(true);
    setError('');
    try {
      await sessionsApi.generateArtwork(sessionId);
      setCritique(null);
      await loadResult();
      triggerCritique();
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Regeneration failed. Please try again.';
      setError(msg);
    } finally {
      setIsRegenerating(false);
    }
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
    const fullUrl = resolveUrl(url);
    const a = document.createElement('a');
    a.href = fullUrl;
    a.download = `muse-generated-${Date.now()}.png`;
    a.target = '_blank';
    a.click();
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[70vh] text-slate-500">
        <Loader2 className="w-8 h-8 animate-spin mr-3" />
        Loading your results…
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
  const allReferences = result?.reference_artworks ?? [];
  const primaryRef = allReferences[0];
  const allGenerations = result?.generated_artworks ?? [];

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
      {/* Header */}
      <div className="flex items-center gap-3 mb-8">
        <button
          onClick={() => navigate(`/session/${sessionId}`)}
          className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-100 transition"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <h1 className="text-2xl font-extrabold text-slate-100 tracking-tight">
            {result?.session_title ?? 'Your Artwork Results'}
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {allGenerations.length} generation{allGenerations.length !== 1 ? 's' : ''} · {latest?.model_provider ?? ''}
          </p>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-6 p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-rose-300 text-sm font-medium">{error}</p>
            <button
              onClick={handleRegenerate}
              className="text-amber-400 hover:underline text-xs mt-1"
            >
              Try regenerating
            </button>
          </div>
        </div>
      )}

      {/* Side-by-side artworks. A session can blend several references, so all
          of them are shown rather than only the first. */}
      {latest && primaryRef && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-10">
          {allReferences.length === 1 ? (
            <ArtworkPanel
              label="Reference Artwork"
              imageUrl={primaryRef.image_url}
              title={primaryRef.title}
              subtitle={`${primaryRef.artist}${primaryRef.year ? ` · ${primaryRef.year}` : ''}`}
            />
          ) : (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3">
                {allReferences.length} Reference Artworks
              </h3>
              <div className="grid grid-cols-2 gap-3">
                {allReferences.map((ref) => (
                  <div
                    key={ref.id}
                    className="rounded-xl overflow-hidden bg-slate-900 border border-slate-800"
                  >
                    <div className="aspect-[4/3] bg-slate-800">
                      <img
                        src={resolveUrl(ref.image_url)}
                        alt={ref.title}
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
          )}
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
        </div>
      )}

      {/* Action buttons */}
      <div className="flex flex-wrap gap-3 mb-10">
        <button
          onClick={handleRegenerate}
          disabled={isRegenerating}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-200 hover:text-white transition disabled:opacity-50 text-sm font-medium"
        >
          {isRegenerating
            ? <><Loader2 className="w-4 h-4 animate-spin" />Regenerating…</>
            : <><RefreshCw className="w-4 h-4" />Regenerate</>
          }
        </button>
        <button
          onClick={handleDownload}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-200 hover:text-white transition text-sm font-medium"
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
              : 'bg-gradient-to-r from-amber-500 to-rose-500 text-slate-950 shadow-lg shadow-amber-500/20'
          }`}
        >
          {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : savedOk ? <CheckCircle2 className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
          {savedOk ? 'Saved to Gallery!' : isSaving ? 'Saving…' : 'Save to Gallery'}
        </button>
      </div>

      {/* Critiques */}
      <div className="space-y-4">
        <h2 className="text-lg font-bold text-slate-100">Artwork Critique</h2>

        {critiqueLoading && (
          <div className="flex items-center gap-3 p-5 bg-slate-900 border border-slate-800 rounded-2xl text-slate-400">
            <Loader2 className="w-5 h-5 animate-spin text-amber-400" />
            <span className="text-sm">Muse is analysing both artworks…</span>
          </div>
        )}

        {critiqueError && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-between gap-3">
            <p className="text-rose-300 text-sm">{critiqueError}</p>
            <button onClick={triggerCritique} className="text-amber-400 hover:underline text-xs flex-shrink-0">
              Retry
            </button>
          </div>
        )}

        {critique && (
          <>
            <ArtworkCritiquePanel label="Reference Artwork Critique" section={critique.reference_critique ?? undefined} />
            <ArtworkCritiquePanel label="Generated Artwork Critique" section={critique.generated_critique ?? undefined} />

            {critique.comparison && (
              <div className="p-5 bg-gradient-to-br from-amber-500/5 to-rose-500/5 border border-amber-500/20 rounded-2xl">
                <h4 className="text-xs font-semibold uppercase tracking-widest text-amber-400 mb-3">Comparative Analysis</h4>
                <p className="text-sm text-slate-300 leading-relaxed">{critique.comparison}</p>
              </div>
            )}
          </>
        )}
      </div>

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
