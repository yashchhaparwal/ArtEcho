import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Palette, Sparkles, ArrowRight, Upload, Clock, CheckCircle2 } from 'lucide-react';
import { api, sessionsApi } from '../services/api';
import type { ChatSession } from '../services/api';
import { useAuth } from '../context/AuthContext';

export const Home: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [activeSessions, setActiveSessions] = useState<ChatSession[]>([]);
  const [health, setHealth] = useState<{ status: string; service: string; version: string } | null>(null);

  useEffect(() => {
    api.get('/health')
      .then((res) => setHealth(res.data))
      .catch((err) => console.error('API health check error:', err));
  }, []);

  useEffect(() => {
    if (!user) return;
    sessionsApi.listUserSessions()
      .then((res) => {
        // Unsaved or active sessions with messages
        const active = res.data.sessions.filter(
          (s) => !s.is_saved && s.messages && s.messages.length > 0
        );
        setActiveSessions(active.slice(0, 3));
      })
      .catch((err) => console.error('Failed to load active sessions:', err));
  }, [user]);

  return (
    <div className="max-w-5xl mx-auto px-6 py-12 flex flex-col items-center justify-center text-center">
      <div className="inline-flex items-center space-x-2 px-4 py-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 text-amber-300 text-sm font-medium mb-6">
        <Palette className="w-4 h-4" />
        <span>Interactive AI Art & Guided Dialogue</span>
      </div>

      <h1 className="text-5xl sm:text-6xl font-extrabold tracking-tight max-w-3xl leading-[1.15] text-slate-100">
        Where Masterpieces Inspire{" "}
        <span className="bg-gradient-to-r from-amber-400 via-rose-400 to-purple-400 bg-clip-text text-transparent">
          New AI Artworks
        </span>
      </h1>

      <p className="mt-6 text-lg text-slate-400 max-w-2xl leading-relaxed">
        Select or upload an iconic public-domain artwork, engage in a guided conversation about visual elements and personal context, and co-create synthesized AI art with an expert critique.
      </p>

      {/* Primary Hero CTAs */}
      <div className="mt-8 flex flex-col sm:flex-row items-center gap-4">
        <Link
          to="/library"
          className="w-full sm:w-auto px-8 py-3.5 rounded-2xl bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 font-bold text-base shadow-xl shadow-amber-500/20 flex items-center justify-center gap-2 transition"
        >
          <Sparkles className="w-5 h-5" />
          Explore Artwork Library
        </Link>
        <Link
          to="/upload"
          className="w-full sm:w-auto px-8 py-3.5 rounded-2xl bg-slate-900 border border-slate-800 text-slate-200 hover:text-white hover:border-slate-700 font-semibold text-base flex items-center justify-center gap-2 transition"
        >
          <Upload className="w-5 h-5" />
          Upload Your Own
        </Link>
      </div>

      {/* Resume Section: Continue Where You Left Off */}
      {user && activeSessions.length > 0 && (
        <div className="mt-12 w-full max-w-3xl bg-slate-900/90 border border-amber-500/30 rounded-3xl p-6 text-left shadow-xl">
          <div className="flex items-center gap-2 text-amber-400 font-semibold text-sm mb-4">
            <Clock className="w-4 h-4" />
            <span>Continue Where You Left Off</span>
          </div>

          <div className="space-y-3">
            {activeSessions.map((session) => (
              <div
                key={session.id}
                onClick={() =>
                  navigate(session.is_ready_to_generate ? `/session/${session.id}/result` : `/session/${session.id}`)
                }
                className="flex items-center justify-between p-4 rounded-2xl bg-slate-950/80 border border-slate-800 hover:border-amber-500/40 cursor-pointer transition group"
              >
                <div className="min-w-0 pr-4">
                  <h4 className="font-semibold text-slate-200 text-sm truncate group-hover:text-amber-300 transition">
                    {session.title}
                  </h4>
                  <p className="text-xs text-slate-500 mt-0.5 truncate">
                    {session.is_ready_to_generate ? 'Ready to generate artwork' : `${session.messages.length} messages in conversation`}
                  </p>
                </div>
                <button className="flex items-center gap-1 text-xs font-semibold text-amber-400 group-hover:translate-x-1 transition flex-shrink-0">
                  <span>Resume</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* API Health Indicator */}
      <div className="mt-10 p-4 rounded-xl bg-slate-900/90 border border-slate-800 flex items-center space-x-3 text-sm text-slate-400">
        <CheckCircle2 className="w-5 h-5 text-emerald-400" />
        <span>
          Backend Status:{' '}
          <strong className="text-slate-200">{health ? health.service : 'Connecting to FastAPI...'}</strong>
          {health && <span className="ml-2 text-xs text-emerald-400">({health.status})</span>}
        </span>
      </div>
    </div>
  );
};
