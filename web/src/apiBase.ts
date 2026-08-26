const DEFAULT_API = "http://127.0.0.1:8000";

function trimBase(base: string): string {
  return base.replace(/\/$/, "");
}

/** Resolve HTTP API base. Empty string = same origin (Vite dev proxy). */
export function apiBase(): string {
  const desktop = window.coderkingDesktop?.apiBase;
  if (desktop) return trimBase(desktop);
  const env = import.meta.env.VITE_API_BASE as string | undefined;
  if (env) return trimBase(env);
  if (import.meta.env.DEV && ["5173", "5188"].includes(window.location.port)) return "";
  if (window.location.protocol === "file:" || !window.location.host) {
    return DEFAULT_API;
  }
  return "";
}

export function apiUrl(path: string): string {
  const base = apiBase();
  const p = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${p}` : p;
}

export function wsUrl(path: string): string {
  const base = apiBase();
  const p = path.startsWith("/") ? path : `/${path}`;
  if (base) {
    const u = new URL(base);
    const proto = u.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${u.host}${p}`;
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${p}`;
}
