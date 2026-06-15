/**
 * Core Web Vitals reporting via PerformanceObserver.
 *
 * Collects LCP (Largest Contentful Paint), FCP (First Contentful Paint),
 * INP (Interaction to Next Paint), and CLS (Cumulative Layout Shift) and
 * sends them to the backend ``/api/client-metrics`` endpoint.
 *
 * Usage — call once at app mount::
 *
 *   import { reportWebVitals } from '@/shared/utils/reportWebVitals';
 *   reportWebVitals();
 */

interface VitalMetric {
  name: string;
  value: number;
  rating: 'good' | 'needs-improvement' | 'poor';
  url: string;
  timestamp: number;
}

const BUFFER: VitalMetric[] = [];
const FLUSH_INTERVAL_MS = 30_000; // flush every 30 seconds

// ── LCP thresholds (https://web.dev/lcp) ──────────────────────────
const LCP_GOOD = 2500;
const LCP_POOR = 4000;

// ── FCP thresholds (https://web.dev/fcp) ──────────────────────────
const FCP_GOOD = 1800;
const FCP_POOR = 3000;

// ── INP thresholds (https://web.dev/inp) ──────────────────────────
const INP_GOOD = 200;
const INP_POOR = 500;

// ── CLS thresholds (https://web.dev/cls) ──────────────────────────
const CLS_GOOD = 0.1;
const CLS_POOR = 0.25;

function ratingFor(name: string, value: number): VitalMetric['rating'] {
  switch (name) {
    case 'LCP':
      return value <= LCP_GOOD ? 'good' : value <= LCP_POOR ? 'needs-improvement' : 'poor';
    case 'FCP':
      return value <= FCP_GOOD ? 'good' : value <= FCP_POOR ? 'needs-improvement' : 'poor';
    case 'INP':
      return value <= INP_GOOD ? 'good' : value <= INP_POOR ? 'needs-improvement' : 'poor';
    case 'CLS':
      return value <= CLS_GOOD ? 'good' : value <= CLS_POOR ? 'needs-improvement' : 'poor';
    default:
      return 'good';
  }
}

function sendToBackend(metric: VitalMetric): void {
  BUFFER.push(metric);
}

function flush(): void {
  if (BUFFER.length === 0) return;
  const metrics = BUFFER.splice(0);
  const payload = JSON.stringify({ metrics });
  if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
    navigator.sendBeacon('/api/client-metrics', payload);
  }
}

// ── Install observers ──────────────────────────────────────────────

function observeLCP(): void {
  try {
    new PerformanceObserver((list) => {
      const entries = list.getEntries();
      if (entries.length === 0) return;
      const lastEntry = entries[entries.length - 1];
      sendToBackend({
        name: 'LCP',
        value: Math.round(lastEntry.startTime),
        rating: ratingFor('LCP', lastEntry.startTime),
        url: window.location.pathname,
        timestamp: Date.now(),
      });
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch {
    // LCP observer not supported
  }
}

function observeFCP(): void {
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.name === 'first-contentful-paint') {
          sendToBackend({
            name: 'FCP',
            value: Math.round(entry.startTime),
            rating: ratingFor('FCP', entry.startTime),
            url: window.location.pathname,
            timestamp: Date.now(),
          });
        }
      }
    }).observe({ type: 'paint', buffered: true });
  } catch {
    // Paint observer not supported
  }
}

function observeINP(): void {
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        sendToBackend({
          name: 'INP',
          value: Math.round(entry.duration),
          rating: ratingFor('INP', entry.duration),
          url: window.location.pathname,
          timestamp: Date.now(),
        });
      }
    }).observe({ type: 'event', buffered: true });
  } catch {
    // Event observer not supported
  }
}

function observeCLS(): void {
  try {
    let cls = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!(entry as any).hadRecentInput) {
          cls += (entry as any).value;
        }
      }
      sendToBackend({
        name: 'CLS',
        value: Math.round(cls * 1000) / 1000,
        rating: ratingFor('CLS', cls),
        url: window.location.pathname,
        timestamp: Date.now(),
      });
    }).observe({ type: 'layout-shift', buffered: true });
  } catch {
    // Layout shift observer not supported
  }
}

// ── Public API ─────────────────────────────────────────────────────

export function reportWebVitals(): void {
  if (typeof window === 'undefined' || typeof PerformanceObserver === 'undefined') {
    return;
  }
  observeLCP();
  observeFCP();
  observeINP();
  observeCLS();

  // Periodic flush.
  setInterval(flush, FLUSH_INTERVAL_MS);
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      flush();
    }
  });
}
