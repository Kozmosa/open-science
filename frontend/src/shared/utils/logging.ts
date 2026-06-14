/**
 * Structured client-side error logging for AINRF.
 *
 * Errors are buffered and flushed to the backend ``/api/client-logs``
 * endpoint periodically via ``navigator.sendBeacon`` (fire-and-forget).
 * Falls back to ``console.error`` when the backend is unavailable.
 */

interface ClientErrorEvent {
  timestamp: string;
  message: string;
  stack?: string;
  url: string;
  userAgent: string;
  requestId?: string;
  metadata?: Record<string, unknown>;
}

const BUFFER: ClientErrorEvent[] = [];
const FLUSH_INTERVAL_MS = 5_000;
let _lastRequestId: string | null = null;

/** Store the most recent X-Request-ID for error correlation. */
export function setLastRequestId(id: string | null): void {
  _lastRequestId = id;
}

function flush(): void {
  if (BUFFER.length === 0) return;
  const events = BUFFER.splice(0);
  const payload = JSON.stringify({ events });
  if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
    navigator.sendBeacon('/api/client-logs', payload);
  }
  // Also log to console for development.
  for (const event of events) {
    console.error('[ainrf]', event.message, event.metadata ?? '');
  }
}

// Periodic flush.
if (typeof window !== 'undefined') {
  setInterval(flush, FLUSH_INTERVAL_MS);
  // Flush on page unload.
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      flush();
    }
  });
}

/**
 * Log a client-side error with optional structured context.
 *
 * @param error - The error object or value to log.
 * @param context - Optional key-value metadata to attach.
 */
export function logError(error: unknown, context?: Record<string, unknown>): void {
  const event: ClientErrorEvent = {
    timestamp: new Date().toISOString(),
    message: error instanceof Error ? error.message : String(error),
    stack: error instanceof Error ? error.stack : undefined,
    url: typeof window !== 'undefined' ? window.location.href : '',
    userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
    requestId: _lastRequestId ?? undefined,
    metadata: context,
  };
  BUFFER.push(event);
  // Immediate console output for development.
  console.error('[ainrf]', event.message, context ?? '');
}
