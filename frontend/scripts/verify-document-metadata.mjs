import { readFile } from 'node:fs/promises';
import { dirname, isAbsolute, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(scriptDir, '..');
const configuredOutDir = process.env.OPENSCIENCE_FRONTEND_OUT_DIR?.trim() || 'dist';
const outDir = isAbsolute(configuredOutDir)
  ? configuredOutDir
  : resolve(frontendRoot, configuredOutDir);

const [html, robots, llms] = await Promise.all([
  readFile(resolve(outDir, 'index.html'), 'utf8'),
  readFile(resolve(outDir, 'robots.txt'), 'utf8'),
  readFile(resolve(outDir, 'llms.txt'), 'utf8'),
]);

const requirements = [
  ['description metadata', html.includes('<meta name="description"')],
  ['private robots metadata', html.includes('name="robots" content="noindex,nofollow,noarchive"')],
  ['light theme color', html.includes('name="theme-color" content="#ffffff"')],
  ['dark theme color', html.includes('name="theme-color" content="#0f0f10"')],
  ['robots crawl denial', /^User-agent: \*\nDisallow: \/\s*$/u.test(robots)],
  ['private llms guidance', llms.includes('private, authenticated research control plane')],
];
const failures = requirements.filter(([, valid]) => !valid).map(([label]) => label);

if (failures.length > 0) {
  throw new Error(`Frontend document metadata verification failed: ${failures.join(', ')}`);
}

process.stdout.write('Frontend document metadata passed.\n');
