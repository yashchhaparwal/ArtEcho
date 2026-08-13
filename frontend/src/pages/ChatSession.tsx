import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, Send, Loader2, Sparkles, Palette, CheckCircle2 } from 'lucide-react';
import { sessionsApi, streamMessage, streamOpeningMessage } from '../services/api';
import { resolveAssetUrl } from '../config';
import type { ChatSession as ChatSessionType, ChatMessage, Artwork } from '../services/api';
import { useAuth } from '../context/AuthContext';

const resolveImageUrl = resolveAssetUrl;

const TypingDots: React.FC = () => (
  <div className="flex items-center gap-1 px-4 py-3">
    {[0, 1, 2].map((i) => (
      <span
        key={i}
        className="w-2 h-2 rounded-full bg-amber-400 animate-bounce"
        style={{ animationDelay: `${i * 0.15}s` }}
      />
    ))}
  </div>
);

const MessageBubble: React.FC<{ msg: ChatMessage }> = ({ msg }) => {
  const isUser = msg.sender === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-amber-500 to-rose-500 flex items-center justify-center flex-shrink-0 mr-3 mt-1 shadow-lg shadow-amber-500/20">
          <Sparkles className="w-4 h-4 text-white" />
        </div>
      )}
      <div
        className={`max-w-[75%] px-4 py-3 rounded-2xl text-sm leading-relaxed shadow-sm ${
          isUser
            ? 'bg-gradient-to-br from-amber-500 to-rose-500 text-slate-950 font-medium rounded-br-sm'
            : 'bg-slate-800 border border-slate-700/60 text-slate-100 rounded-bl-sm'
        }`}
      >
        {msg.content}
      </div>
    </div>
  );
};

const ArtworkPin: React.FC<{ artwork: Artwork }> = ({ artwork }) => {
  const [imgError, setImgError] = useState(false);
  return (
    <div className="flex items-center gap-3 p-3 bg-slate-900 border border-slate-800 rounded-xl">
      <div className="w-12 h-12 rounded-lg overflow-hidden bg-slate-800 flex-shrink-0">
        {!imgError ? (
          <img
            src={resolveImageUrl(artwork.image_url)}
            alt={artwork.title}
            className="w-full h-full object-cover"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center" style={{ backgroundColor: artwork.dominant_color ?? '#1e293b' }}>
            <Palette className="w-5 h-5 text-white/30" />
          </div>
        )}
      </div>
      <div className="min-w-0">
        <p className="text-xs font-semibold text-slate-200 truncate">{artwork.title}</p>
        <p className="text-xs text-slate-500 truncate">{artwork.artist}{artwork.year ? ` · ${artwork.year}` : ''}</p>
      </div>
    </div>
  );
};

export const ChatSessionPage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const { user, loading } = useAuth();

  const [session, setSession] = useState<ChatSessionType | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [genError, setGenError] = useState('');
  const [streamingText, setStreamingText] = useState('');
  /** Slow prerequisite before the first token, e.g. reading an upload. */
  const [assistantStatus, setAssistantStatus] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortStreamRef = useRef<(() => void) | null>(null);
  // Guards the opening request against strict-mode double effects.
  const openingStartedRef = useRef(false);

  // Drop the connection if the user navigates away mid-reply.
  useEffect(() => () => abortStreamRef.current?.(), []);

  const scrollToBottom = useCallback(() => {
    // Scroll the thread itself, not the element into view. `scrollIntoView`
    // walks up and scrolls every scrollable ancestor including the window,
    // which dragged the page header off screen on a short conversation.
    const el = threadRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, []);

  /**
   * Stream the opening question into a session that has none yet.
   *
   * Creating a session returns immediately now, so a brand-new thread arrives
   * empty and the first question types itself in here — the same treatment
   * every later reply already gets.
   */
  const requestOpeningMessage = useCallback(() => {
    if (!sessionId || openingStartedRef.current) return;
    openingStartedRef.current = true;

    setIsSending(true);
    setStreamingText('');

    abortStreamRef.current = streamOpeningMessage(sessionId, {
      onStatus: (detail) => setAssistantStatus(detail),
      onToken: (text) => {
        setAssistantStatus('');
        setStreamingText((prev) => prev + text);
      },
      onDone: (payload) => {
        setMessages((prev) =>
          prev.some((m) => m.id === payload.id)
            ? prev
            : [...prev, {
                id: payload.id,
                session_id: payload.session_id,
                sender: 'assistant',
                content: payload.content,
                created_at: payload.created_at,
              }]
        );
        setIsSending(false);
        setStreamingText('');
        setAssistantStatus('');
        abortStreamRef.current = null;
        inputRef.current?.focus();
      },
      onError: (detail) => {
        setError(`Could not start the conversation: ${detail}`);
        setIsSending(false);
        setStreamingText('');
        setAssistantStatus('');
        abortStreamRef.current = null;
        // Let the user retry via the banner.
        openingStartedRef.current = false;
      },
    });
  }, [sessionId]);

  const loadSession = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await sessionsApi.getById(sessionId);
      setSession(res.data);
      setMessages(res.data.messages);
      if (res.data.messages.length === 0) requestOpeningMessage();
    } catch {
      setError('Failed to load session. It may not exist or you may not have access.');
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, requestOpeningMessage]);

  useEffect(() => {
    // Wait for auth loading to finish before deciding to redirect.
    if (loading) return;
    if (!user) {
      navigate('/login');
      return;
    }
    loadSession();
  }, [user, loading, loadSession, navigate]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  const handleSend = async () => {
    const content = inputValue.trim();
    // Being "ready to generate" no longer ends the conversation — the client
    // wants session length left to the user, so they can keep talking as long
    // as they like and generate whenever they choose.
    if (!content || isSending || !sessionId) return;

    // Optimistic UI: show user message immediately
    const optimisticMsg: ChatMessage = {
      id: `tmp-${Date.now()}`,
      session_id: sessionId,
      sender: 'user',
      content,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticMsg]);
    setInputValue('');
    setIsSending(true);
    setStreamingText('');
    setError('');

    const finish = () => {
      setIsSending(false);
      setStreamingText('');
      abortStreamRef.current = null;
      inputRef.current?.focus();
    };

    // Stream the reply so text appears as it is written. A local CPU model can
    // take minutes to finish a turn; waiting for the whole thing looks hung.
    abortStreamRef.current = streamMessage(sessionId, content, {
      onToken: (text) => setStreamingText((prev) => prev + text),
      onDone: (payload) => {
        setMessages((prev) =>
          prev.some((m) => m.id === payload.id)
            ? prev
            : [...prev, {
                id: payload.id,
                session_id: payload.session_id,
                sender: 'assistant',
                content: payload.content,
                created_at: payload.created_at,
              }]
        );
        setSession((prev) =>
          prev
            ? { ...prev, is_ready_to_generate: prev.is_ready_to_generate || payload.ready_to_generate }
            : prev
        );
        // The composer reopens here. Context extraction is still running on the
        // server and reports back via onContext; re-fetching the session now
        // would only read the pre-extraction state.
        finish();
      },
      onContext: (payload) => {
        setSession((prev) =>
          prev
            ? {
                ...prev,
                context_summary: payload.context_summary,
                is_ready_to_generate: prev.is_ready_to_generate || payload.ready_to_generate,
              }
            : prev
        );
      },
      onError: async (detail) => {
        console.error('Streaming failed, falling back to the blocking endpoint', detail);
        // The SSE path can fail behind proxies that buffer responses; the
        // blocking endpoint produces the same end state, just slower.
        try {
          const res = await sessionsApi.sendMessage(sessionId, content);
          setMessages((prev) =>
            prev.some((m) => m.id === res.data.id) ? prev : [...prev, res.data]
          );
          const sessionRes = await sessionsApi.getById(sessionId);
          setSession(sessionRes.data);
        } catch {
          setError('Failed to send message. Please try again.');
          setMessages((prev) => prev.filter((m) => m.id !== optimisticMsg.id));
        } finally {
          finish();
        }
      },
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const referenceArtworks = session?.session_references
    .map((ref) => ref.reference_artwork)
    .filter(Boolean) as Artwork[] ?? [];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[70vh] text-slate-500">
        <Loader2 className="w-8 h-8 animate-spin mr-3" />
        Loading conversation…
      </div>
    );
  }

  if (error && !session) {
    return (
      <div className="max-w-xl mx-auto px-4 py-16 text-center">
        <p className="text-rose-400 text-base mb-4">{error}</p>
        <Link to="/library" className="text-amber-400 hover:underline text-sm">Back to Library</Link>
      </div>
    );
  }


  const handleGenerate = async (force = false) => {
    if (!sessionId || isGenerating) return;
    setIsGenerating(true);
    setGenError('');
    try {
      // Only queues the job — it comes back in milliseconds. The result page
      // follows the job from here, so the user watches it happen instead of
      // sitting on a frozen button for the ~45s the image actually takes.
      const res = await sessionsApi.startGeneration(sessionId, force);
      navigate(`/session/${sessionId}/result`, { state: { jobId: res.data.job_id } });
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Image generation failed. Please try again.';
      setGenError(msg);
      setIsGenerating(false);
    }
    // On success we've navigated away — leave `isGenerating` set so the button
    // can't be fired twice during the transition.
  };

  const userTurns = messages.filter((m) => m.sender === 'user').length;
  const isReady = Boolean(session?.is_ready_to_generate);
  // Before the assistant flags readiness, the user can still choose to generate
  // early once they've said something — a short session is their call to make.
  const canGenerateEarly = !isReady && userTurns >= 1;

  return (
    // Height tracks the navbar's own responsive height (h-16 / sm:h-20) so the
    // thread fills the viewport exactly and never spills into a page scroll.
    // `dvh` keeps it honest on mobile, where the browser chrome comes and goes.
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-4 sm:py-6 flex flex-col h-[calc(100dvh-4rem)] sm:h-[calc(100dvh-5rem)]">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/library')}
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-slate-100 transition"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="text-lg font-bold text-slate-100 leading-tight">{session?.title ?? 'Art Conversation'}</h1>
            <p className="text-xs text-slate-500">{messages.length} message{messages.length !== 1 ? 's' : ''}</p>
          </div>
        </div>

        {/* Reference Artwork Pins */}
        {referenceArtworks.length > 0 && (
          <div className="flex gap-2 flex-wrap justify-end">
            {referenceArtworks.map((art) => (
              <ArtworkPin key={art.id} artwork={art} />
            ))}
          </div>
        )}
      </div>

      {/* Generation error alert */}
      {genError && (
        <div className="mb-4 p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-between text-rose-300 text-sm">
          <span>{genError}</span>
          <button
            onClick={() => handleGenerate(!isReady)}
            className="text-amber-400 font-semibold hover:underline ml-3"
          >
            Retry
          </button>
        </div>
      )}

      {/* Ready-to-generate banner. Generating is now an option, not an ending —
          the conversation stays open for as long as the user wants it. */}
      {isReady && (
        <div className="mb-4 p-4 rounded-2xl bg-gradient-to-r from-amber-500/10 to-rose-500/10 border border-amber-500/30 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0" />
            <p className="text-sm text-slate-200 font-medium">
              Muse has enough to work with — generate whenever you like, or keep talking to refine it.
            </p>
          </div>
          <button
            onClick={() => handleGenerate(false)}
            disabled={isGenerating}
            className="flex-shrink-0 flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 font-semibold shadow-lg shadow-amber-500/20 transition text-sm disabled:opacity-60"
          >
            {isGenerating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {isGenerating ? 'Synthesizing Artwork…' : 'Generate My Artwork'}
          </button>
        </div>
      )}

      {/* Message Thread */}
      <div ref={threadRef} className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-1 scrollbar-slim">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        {isSending && (
          <div className="flex justify-start mb-4">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-amber-500 to-rose-500 flex items-center justify-center flex-shrink-0 mr-3 mt-1">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <div className="bg-slate-800 border border-slate-700/60 rounded-2xl rounded-bl-sm max-w-[75%]">
              {streamingText ? (
                <p className="px-4 py-3 text-sm leading-relaxed text-slate-100 whitespace-pre-wrap">
                  {streamingText}
                  <span className="inline-block w-1.5 h-4 ml-0.5 -mb-0.5 bg-amber-400 animate-pulse" />
                </p>
              ) : assistantStatus ? (
                // Vision on an upload runs before any token can arrive; say so
                // rather than showing dots for half a minute.
                <div className="flex items-center gap-2.5 px-4 py-3">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-400" />
                  <span className="text-sm text-slate-400">{assistantStatus}…</span>
                </div>
              ) : (
                <TypingDots />
              )}
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area — always available. The conversation ends when the user
          decides it does, whether that's after two turns or twenty. */}
      <div className="mt-4 flex-shrink-0">
        <div className="flex items-end gap-3 p-3 bg-slate-900 border border-slate-800 rounded-2xl focus-within:border-amber-500/40 transition">
          <textarea
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isReady
                ? 'Keep refining, or generate your artwork above…'
                : 'Share your thoughts about this artwork…'
            }
            rows={2}
            className="flex-1 bg-transparent text-slate-100 placeholder-slate-500 text-sm resize-none focus:outline-none leading-relaxed"
            disabled={isSending}
          />
          <button
            onClick={handleSend}
            disabled={!inputValue.trim() || isSending}
            className="flex-shrink-0 w-9 h-9 rounded-xl bg-gradient-to-br from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 flex items-center justify-center transition disabled:opacity-40 disabled:cursor-not-allowed shadow-md shadow-amber-500/20"
          >
            {isSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>

        <div className="flex items-center justify-center gap-3 mt-2 flex-wrap">
          <p className="text-xs text-slate-600">
            Press <kbd className="px-1 py-0.5 rounded bg-slate-800 text-slate-400">Enter</kbd> to send · <kbd className="px-1 py-0.5 rounded bg-slate-800 text-slate-400">Shift+Enter</kbd> for newline
          </p>
          {canGenerateEarly && (
            <button
              onClick={() => handleGenerate(true)}
              disabled={isGenerating || isSending}
              className="text-xs text-amber-400/90 hover:text-amber-300 underline underline-offset-2 disabled:opacity-50"
            >
              {isGenerating ? 'Generating…' : "I've said enough — generate now"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
