const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const SESSION_ID_KEY = "el-access-session-id";
const SESSION_STARTED_KEY = "el-access-session-started";
const LAST_PATH_KEY = "el-access-last-path";
const LAST_ACTIVITY_KEY = "el-access-last-activity";
const SESSION_IDLE_MS = 30 * 60 * 1000;

function createSessionId(): string {
  if (window.crypto.randomUUID) return window.crypto.randomUUID();
  const bytes = window.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

function sessionId(): string {
  let value = window.sessionStorage.getItem(SESSION_ID_KEY);
  if (!value) {
    value = createSessionId();
    window.sessionStorage.setItem(SESSION_ID_KEY, value);
  }
  return value;
}

function send(eventType: "session_start" | "page_view", path: string) {
  void fetch(`${apiBaseUrl}/api/analytics/access`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId: sessionId(), eventType, path }),
    keepalive: true,
  }).catch(() => undefined);
}

export function trackDashboardAccess(path: string) {
  try {
    const now = Date.now();
    const lastActivity = Number(window.sessionStorage.getItem(LAST_ACTIVITY_KEY) ?? 0);
    if (lastActivity && now - lastActivity > SESSION_IDLE_MS) {
      window.sessionStorage.removeItem(SESSION_ID_KEY);
      window.sessionStorage.removeItem(SESSION_STARTED_KEY);
      window.sessionStorage.removeItem(LAST_PATH_KEY);
    }
    window.sessionStorage.setItem(LAST_ACTIVITY_KEY, String(now));
    const normalizedPath = path || "/";
    if (!window.sessionStorage.getItem(SESSION_STARTED_KEY)) {
      window.sessionStorage.setItem(SESSION_STARTED_KEY, "1");
      send("session_start", normalizedPath);
    }
    if (window.sessionStorage.getItem(LAST_PATH_KEY) !== normalizedPath) {
      window.sessionStorage.setItem(LAST_PATH_KEY, normalizedPath);
      send("page_view", normalizedPath);
    }
  } catch {
    // Analytics must never prevent the dashboard from rendering.
  }
}
