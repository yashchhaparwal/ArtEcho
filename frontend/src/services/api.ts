import axios from 'axios';
import { API_BASE_URL } from '../config';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('muse_access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

export interface UserProfile {
  id: string;
  email: string;
  name?: string;
  is_active: boolean;
  created_at: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
}

export interface Artwork {
  id: string;
  title: string;
  artist: string;
  year?: string;
  movement_style?: string;
  medium?: string;
  description?: string;
  source_attribution?: string;
  image_url: string;
  dominant_color?: string;
  is_public_domain: boolean;
  is_custom_upload: boolean;
  uploaded_by_user_id?: string;
  /** What the local vision model saw in the image; absent until analysed. */
  visual_analysis?: Record<string, string>;
  created_at: string;
}

export interface ArtworkListResponse {
  artworks: Artwork[];
  total: number;
  page: number;
  page_size: number;
}

export interface ArtworkFilters {
  search?: string;
  artist?: string;
  movement?: string;
  include_uploads?: boolean;
  page?: number;
  page_size?: number;
}

export const artworksApi = {
  list: (filters: ArtworkFilters = {}) =>
    api.get<ArtworkListResponse>('/artworks', { params: filters }),

  getById: (id: string) =>
    api.get<Artwork>(`/artworks/${id}`),

  upload: (files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    return api.post<Artwork[]>('/artworks/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

// --- Phase 3 & 4 Session & Generation Types ---

export interface ChatMessage {
  id: string;
  session_id: string;
  sender: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
}

export interface SessionReference {
  id: string;
  session_id: string;
  reference_artwork_id?: string;
  custom_image_url?: string;
  is_custom_upload: boolean;
  reference_artwork?: Artwork;
  created_at: string;
}

export interface ContextSummary {
  artistic_preferences?: string;
  personal_context?: string;
  desired_mood?: string;
  color_palette_notes?: string;
  composition_notes?: string;
  inspiration_level?: 'loose' | 'balanced' | 'near';
}

export interface ChatSession {
  id: string;
  user_id: string;
  title: string;
  status: 'active' | 'completed' | 'archived';
  context_summary?: ContextSummary;
  is_ready_to_generate: boolean;
  is_saved: boolean;
  saved_at?: string;
  created_at: string;
  updated_at: string;
  session_references: SessionReference[];
  messages: ChatMessage[];
}

export interface SessionListResponse {
  sessions: ChatSession[];
  total: number;
}

export interface CritiqueSection {
  composition?: string;
  color_theory?: string;
  symbolism?: string;
  emotional_impact?: string;
  strengths?: string[];
  weaknesses?: string[];
}

export interface CritiqueResponse {
  id: string;
  generated_artwork_id: string;
  reference_critique?: CritiqueSection;
  generated_critique?: CritiqueSection;
  comparison?: string;
  created_at: string;
}

export interface GeneratedArtworkResponse {
  id: string;
  session_id: string;
  image_url: string;
  prompt_synthesized: string;
  inspiration_level: string;
  resolution: string;
  model_provider: string;
  generation_index: number;
  created_at: string;
  critique?: CritiqueResponse;
}

export interface SessionResultResponse {
  session_id: string;
  session_title: string;
  context_summary?: ContextSummary;
  reference_artworks: Artwork[];
  generated_artworks: GeneratedArtworkResponse[];
  latest_generated?: GeneratedArtworkResponse;
  is_ready_to_generate: boolean;
}

// --- Phase 5 Gallery Types ---

export interface GalleryItem {
  session_id: string;
  title: string;
  is_saved: boolean;
  saved_at?: string;
  created_at: string;
  reference_artwork?: Artwork;
  latest_generated_artwork?: GeneratedArtworkResponse;
  context_summary?: ContextSummary;
}

export interface GalleryListResponse {
  items: GalleryItem[];
  total: number;
}

export interface StreamCallbacks {
  onToken: (text: string) => void;
  onDone: (payload: ChatMessage & { ready_to_generate: boolean }) => void;
  onError: (detail: string) => void;
  /** Slow prerequisite the server is working through before any token arrives
   *  (currently vision analysis of an upload). */
  onStatus?: (detail: string) => void;
  /**
   * Arrives AFTER `onDone`. The server extracts the conversation context in a
   * second LLM call, which it now runs once the reply is already on screen and
   * the composer is usable again — so this lands late and quietly updates
   * readiness rather than holding the turn open.
   */
  onContext?: (payload: {
    context_summary: ContextSummary;
    ready_to_generate: boolean;
  }) => void;
}

/** Shared SSE consumer for the streaming chat endpoints. Returns an abort fn. */
function consumeMessageStream(
  path: string,
  body: unknown,
  callbacks: StreamCallbacks
): () => void {
  const controller = new AbortController();
  const token = localStorage.getItem('muse_access_token');

  (async () => {
    try {
      const res = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        throw new Error(`Request failed with status ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line; keep any partial tail.
        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';

        for (const frame of frames) {
          const line = frame.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          const payload = JSON.parse(line.slice(6));
          if (payload.type === 'token') callbacks.onToken(payload.text);
          else if (payload.type === 'status') callbacks.onStatus?.(payload.detail);
          else if (payload.type === 'done') callbacks.onDone(payload);
          else if (payload.type === 'context') callbacks.onContext?.(payload);
          else if (payload.type === 'error') callbacks.onError(payload.detail);
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
      callbacks.onError((err as Error).message || 'Streaming failed');
    }
  })();

  return () => controller.abort();
}

/**
 * Stream an assistant reply over Server-Sent Events.
 *
 * The blocking /messages endpoint can't return until the whole reply is
 * generated, which on a CPU-only local model means the user stares at a typing
 * indicator for minutes. This shows the reply as it is written instead.
 *
 * Returns an abort function.
 */
export function streamMessage(
  sessionId: string,
  content: string,
  callbacks: StreamCallbacks
): () => void {
  return consumeMessageStream(`/sessions/${sessionId}/messages/stream`, { content }, callbacks);
}

/**
 * Stream the assistant's opening question into a brand-new session.
 *
 * Session creation no longer writes this inline — that blocked the "Start a
 * Conversation" click for 13-39s on a local CPU model. The chat page opens
 * immediately and calls this to fill the empty thread.
 *
 * Safe to call more than once: the server replays the existing message rather
 * than generating a second one.
 */
export function streamOpeningMessage(
  sessionId: string,
  callbacks: StreamCallbacks
): () => void {
  return consumeMessageStream(
    `/sessions/${sessionId}/messages/opening/stream`,
    undefined,
    callbacks
  );
}

// --- Long-running job types ---------------------------------------------------

export type JobStatus = 'pending' | 'running' | 'done' | 'error';

/**
 * Image generation and critique are slow enough (a cold generation on the free
 * Pollinations tier measures ~45s) that the server runs them on a worker thread
 * and hands back one of these to poll, rather than holding the request open.
 */
export interface JobResponse<T> {
  job_id: string | null;
  kind: 'generate' | 'critique';
  session_id: string;
  status: JobStatus;
  /** Human-readable step, e.g. "Painting your artwork" — shown in the UI. */
  stage: string;
  elapsed_seconds: number;
  result: T | null;
  error: string | null;
}

export class JobFailedError extends Error {}

/**
 * Poll a job to completion.
 *
 * `onProgress` fires on every tick so the caller can show a live stage and
 * elapsed time — without it the user stares at a spinner for 45 seconds with
 * no way to tell the app apart from a hung one.
 *
 * Returns the job's result. Pass `signal` to stop polling when the component
 * unmounts; the job keeps running server-side either way.
 */
export async function pollJob<T>(
  sessionId: string,
  jobId: string,
  opts: {
    onProgress?: (job: JobResponse<T>) => void;
    intervalMs?: number;
    signal?: AbortSignal;
  } = {}
): Promise<T> {
  const { onProgress, intervalMs = 1200, signal } = opts;

  for (;;) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');

    const res = await api.get<JobResponse<T>>(`/sessions/${sessionId}/jobs/${jobId}`, { signal });
    const job = res.data;
    onProgress?.(job);

    if (job.status === 'done') {
      if (job.result === null) throw new JobFailedError('Job finished without a result.');
      return job.result;
    }
    if (job.status === 'error') {
      throw new JobFailedError(job.error || 'The job failed.');
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export const sessionsApi = {
  create: (referenceArtworkIds: string[]) =>
    api.post<ChatSession>('/sessions', { reference_artwork_ids: referenceArtworkIds }),

  getById: (sessionId: string) =>
    api.get<ChatSession>(`/sessions/${sessionId}`),

  listUserSessions: () =>
    api.get<SessionListResponse>('/sessions'),

  sendMessage: (sessionId: string, content: string) =>
    api.post<ChatMessage>(`/sessions/${sessionId}/messages`, { content }),

  /**
   * Start a generation. Resolves as soon as the job is queued (~instantly);
   * feed the returned `job_id` to `pollJob` to follow it.
   *
   * `force` lets the user generate before the assistant flags the session ready.
   */
  startGeneration: (sessionId: string, force = false) =>
    api.post<JobResponse<GeneratedArtworkResponse>>(
      `/sessions/${sessionId}/generate`,
      undefined,
      { params: force ? { force: true } : undefined }
    ),

  /** Start a critique of the latest generation. Already-critiqued sessions come
   *  back immediately with `status: 'done'` and no job to poll. */
  startCritique: (sessionId: string) =>
    api.post<JobResponse<CritiqueResponse>>(`/sessions/${sessionId}/critique`),

  getResult: (sessionId: string) =>
    api.get<SessionResultResponse>(`/sessions/${sessionId}/result`),

  saveSession: (sessionId: string) =>
    api.post<ChatSession>(`/sessions/${sessionId}/save`),

  deleteSession: (sessionId: string) =>
    api.delete<{ message: string }>(`/sessions/${sessionId}`),
};

export const galleryApi = {
  getSaved: () => api.get<GalleryListResponse>('/gallery'),
};
