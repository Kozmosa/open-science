import { setupWorker } from 'msw/browser';
import { frontendMockHandlers } from './mockHandlers';

const worker = setupWorker(...frontendMockHandlers);

export async function startMockBrowser(): Promise<void> {
  await worker.start({
    quiet: true,
    serviceWorker: { url: '/mockServiceWorker.js' },
    onUnhandledRequest(request, print) {
      if (new URL(request.url).pathname.startsWith('/api/')) {
        print.error();
      }
    },
  });
}
