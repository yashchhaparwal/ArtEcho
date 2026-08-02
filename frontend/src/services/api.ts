import axios from 'axios';

const API_BASE_URL = 'http://localhost:8000/api/v1';

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
  const controller = new AbortController();
  const token = localStorage.getItem('muse_access_token');

  (async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/sessions/${sessionId}/messages/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ content }),
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
          else if (payload.type === 'done') callbacks.onDone(payload);
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

export const sessionsApi = {
  create: (referenceArtworkIds: string[]) =>
    api.post<ChatSession>('/sessions', { reference_artwork_ids: referenceArtworkIds }),

  getById: (sessionId: string) =>
    api.get<ChatSession>(`/sessions/${sessionId}`),

  listUserSessions: () =>
    api.get<SessionListResponse>('/sessions'),

  sendMessage: (sessionId: string, content: string) =>
    api.post<ChatMessage>(`/sessions/${sessionId}/messages`, { content }),

  /** `force` lets the user generate before the assistant flags the session ready. */
  generateArtwork: (sessionId: string, force = false) =>
    api.post<GeneratedArtworkResponse>(
      `/sessions/${sessionId}/generate`,
      undefined,
      { params: force ? { force: true } : undefined }
    ),

  generateCritique: (sessionId: string) =>
    api.post<CritiqueResponse>(`/sessions/${sessionId}/critique`),

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
