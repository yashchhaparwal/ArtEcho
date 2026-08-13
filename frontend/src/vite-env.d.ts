/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin, e.g. https://muse-api.example.com. Defaults to localhost:8000 in dev. */
  readonly VITE_API_ORIGIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
