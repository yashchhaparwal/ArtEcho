/**
 * Where the backend lives.
 *
 * The origin was hardcoded to http://localhost:8000 in six separate files,
 * which made the app undeployable: a hosted build would ask each visitor's own
 * machine for the API. It now comes from one place, and from the environment.
 *
 * Set `VITE_API_ORIGIN` at build time (Vercel project settings, or a local
 * .env file — see .env.example). Vite inlines it into the bundle, so it must be
 * present when the build runs, not at runtime.
 */

const RAW_ORIGIN = import.meta.env.VITE_API_ORIGIN ?? 'http://localhost:8000';

/** Backend origin with any trailing slash removed, e.g. https://api.example.com */
export const API_ORIGIN = RAW_ORIGIN.replace(/\/+$/, '');

/** Base for the versioned JSON API. */
export const API_BASE_URL = `${API_ORIGIN}/api/v1`;

/**
 * Absolute URL for an image the backend reports.
 *
 * Library artworks carry absolute Wikimedia URLs, while uploads and generated
 * pieces are server-relative paths like `/generated/<id>.jpg`, so only the
 * latter need the origin prepended.
 */
export function resolveAssetUrl(url?: string | null): string {
  if (!url) return '';
  return url.startsWith('/') ? `${API_ORIGIN}${url}` : url;
}
