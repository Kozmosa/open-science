import { setupWorker } from 'msw/browser';
import { legacyMockHandlers } from './mockHandlers';

const worker = setupWorker(...legacyMockHandlers);

export async function startMockBrowser(): Promise<void> {
  await worker.start({
    quiet: true,
    serviceWorker: { url: '/mockServiceWorker.js' },
    onUnhandledRequest: 'bypass',
  });
}
