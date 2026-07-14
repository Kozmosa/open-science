import { readFile, readdir, stat } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
import { dirname, isAbsolute, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(scriptDir, '..');
const configuredOutDir = process.env.OPENSCIENCE_FRONTEND_OUT_DIR?.trim() || 'dist';
const outDir = isAbsolute(configuredOutDir)
  ? configuredOutDir
  : resolve(frontendRoot, configuredOutDir);
const manifestPath = resolve(outDir, '.vite/manifest.json');

const KIB = 1024;
const MIB = 1024 * KIB;
const budgets = {
  // Radix Toast and FocusScope are now part of the authenticated shell's
  // accessibility baseline. Keep the compressed ceiling fixed while allowing
  // the small raw-module overhead of those primitives.
  entry: { raw: 800 * KIB, gzip: 250 * KIB },
  fileBrowserBeforeEditor: { raw: 850 * KIB, gzip: 300 * KIB },
  monacoIncremental: { raw: 4 * MIB, gzip: 1100 * KIB },
};
const defaultChunkLimit = 500_000;
const allowedLargeAssets = [
  { pattern: /^editor\.api2-.*\.js$/, limit: 3_700_000, reason: 'lazy Monaco editor core' },
  { pattern: /^ts\.worker-.*\.js$/, limit: 7_100_000, reason: 'lazy Monaco TypeScript worker' },
  { pattern: /^css\.worker-.*\.js$/, limit: 1_100_000, reason: 'lazy Monaco CSS worker' },
  { pattern: /^html\.worker-.*\.js$/, limit: 750_000, reason: 'lazy Monaco HTML worker' },
  { pattern: /^json\.worker-.*\.js$/, limit: 450_000, reason: 'lazy Monaco JSON worker' },
];
const monacoStaticTokens = ['monaco', 'editor.api'];
const terminalStaticTokens = ['terminal-vendor', 'xterm'];

function formatBytes(value) {
  return `${(value / KIB).toFixed(1)} KiB`;
}

function chunkIdentity(key, chunk) {
  return [key, chunk.file, chunk.name, chunk.src]
    .filter((value) => typeof value === 'string')
    .join(' ')
    .toLowerCase();
}

function collectStaticClosure(manifest, startKey) {
  const closure = new Set();
  const pending = [startKey];

  while (pending.length > 0) {
    const key = pending.pop();
    if (!key || closure.has(key)) {
      continue;
    }
    const chunk = manifest[key];
    if (!chunk) {
      throw new Error(`Manifest import ${key} is missing`);
    }
    closure.add(key);
    pending.push(...(chunk.imports ?? []));
  }

  return closure;
}

async function measureJavaScript(manifest, keys) {
  const files = new Set(
    [...keys]
      .map((key) => manifest[key]?.file)
      .filter((file) => typeof file === 'string' && file.endsWith('.js')),
  );
  let raw = 0;
  let gzip = 0;

  for (const file of files) {
    const content = await readFile(resolve(outDir, file));
    raw += content.byteLength;
    gzip += gzipSync(content).byteLength;
  }

  return { raw, gzip, files };
}

function assertBudget(label, measured, budget, failures) {
  if (measured.raw > budget.raw || measured.gzip > budget.gzip) {
    failures.push(
      `${label} is ${formatBytes(measured.raw)} raw / ${formatBytes(measured.gzip)} gzip; ` +
        `limits are ${formatBytes(budget.raw)} raw / ${formatBytes(budget.gzip)} gzip`,
    );
  }
}

async function main() {
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  const failures = [];
  const entryKeys = Object.entries(manifest)
    .filter(([, chunk]) => chunk.isEntry)
    .map(([key]) => key);

  if (entryKeys.length !== 1) {
    throw new Error(`Expected one frontend entry in ${manifestPath}, found ${entryKeys.length}`);
  }

  const entryKey = entryKeys[0];
  const fileBrowserKey = 'src/pages/FileBrowserPage.tsx';
  const monacoKey = 'src/components/file-browser/MonacoTextViewer.tsx';
  const fileBrowserChunk = manifest[fileBrowserKey];
  const monacoChunk = manifest[monacoKey];

  if (!fileBrowserChunk?.isDynamicEntry || !monacoChunk?.isDynamicEntry) {
    throw new Error('FileBrowserPage and MonacoTextViewer must remain dynamic entries');
  }
  if (!(fileBrowserChunk.dynamicImports ?? []).includes(monacoKey)) {
    failures.push('FileBrowserPage must load MonacoTextViewer through a dynamic import');
  }

  const entryClosure = collectStaticClosure(manifest, entryKey);
  const fileBrowserClosure = collectStaticClosure(manifest, fileBrowserKey);
  const monacoClosure = collectStaticClosure(manifest, monacoKey);
  const monacoIncrementalClosure = new Set(
    [...monacoClosure].filter((key) => !fileBrowserClosure.has(key)),
  );

  const pagePolicies = Object.keys(manifest)
    .filter((key) => key.startsWith('src/pages/') && key.endsWith('Page.tsx'))
    .map((key) => ({
      label: key,
      closure: collectStaticClosure(manifest, key),
      forbiddenTokens: [
        ...monacoStaticTokens,
        ...(/\/(Terminal|Dashboard)Page\.tsx$/.test(key) ? [] : terminalStaticTokens),
      ],
    }));
  const staticPolicies = [
    {
      label: 'entry',
      closure: entryClosure,
      forbiddenTokens: [...monacoStaticTokens, ...terminalStaticTokens],
    },
    ...pagePolicies,
  ];

  for (const { label, closure, forbiddenTokens } of staticPolicies) {
    for (const key of closure) {
      const identity = chunkIdentity(key, manifest[key]);
      const token = forbiddenTokens.find((candidate) => identity.includes(candidate));
      if (token) {
        failures.push(`${label} static closure contains forbidden dependency ${token}: ${key}`);
      }
    }
  }

  const entrySize = await measureJavaScript(manifest, entryClosure);
  const fileBrowserSize = await measureJavaScript(manifest, fileBrowserClosure);
  const monacoSize = await measureJavaScript(manifest, monacoIncrementalClosure);
  assertBudget('Entry static JavaScript', entrySize, budgets.entry, failures);
  assertBudget(
    'FileBrowser static JavaScript before opening a text file',
    fileBrowserSize,
    budgets.fileBrowserBeforeEditor,
    failures,
  );
  assertBudget('Incremental lazy Monaco JavaScript', monacoSize, budgets.monacoIncremental, failures);

  const assetDir = resolve(outDir, 'assets');
  const assetNames = await readdir(assetDir);
  const allowedOversizedAssets = [];
  for (const assetName of assetNames.filter((name) => name.endsWith('.js'))) {
    const size = (await stat(resolve(assetDir, assetName))).size;
    if (size <= defaultChunkLimit) {
      continue;
    }
    const allowance = allowedLargeAssets.find(({ pattern }) => pattern.test(assetName));
    if (!allowance) {
      failures.push(
        `${assetName} is ${formatBytes(size)}; non-allowlisted JavaScript must stay below ` +
          formatBytes(defaultChunkLimit),
      );
      continue;
    }
    if (size > allowance.limit) {
      failures.push(
        `${assetName} is ${formatBytes(size)}; ${allowance.reason} limit is ` +
          formatBytes(allowance.limit),
      );
      continue;
    }
    allowedOversizedAssets.push(`${assetName} (${formatBytes(size)}, ${allowance.reason})`);
  }

  if (failures.length > 0) {
    throw new Error(`Bundle budget failed:\n- ${failures.join('\n- ')}`);
  }

  console.log('Bundle budget passed:');
  console.log(
    `- entry static JS: ${formatBytes(entrySize.raw)} raw / ${formatBytes(entrySize.gzip)} gzip`,
  );
  console.log(
    `- FileBrowser before editor: ${formatBytes(fileBrowserSize.raw)} raw / ` +
      `${formatBytes(fileBrowserSize.gzip)} gzip`,
  );
  console.log(
    `- incremental lazy Monaco: ${formatBytes(monacoSize.raw)} raw / ` +
      `${formatBytes(monacoSize.gzip)} gzip`,
  );
  console.log(`- allowlisted oversized assets: ${allowedOversizedAssets.join(', ')}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
