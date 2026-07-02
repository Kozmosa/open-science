/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK?: string;
  readonly VITE_AINRF_API_KEY?: string;
  readonly VITE_OPENSCIENCE_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
