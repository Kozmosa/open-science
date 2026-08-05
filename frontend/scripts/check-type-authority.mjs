import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve, relative, join } from 'node:path';

const frontendRoot = resolve(new URL('..', import.meta.url).pathname);
const sourceRoot = resolve(frontendRoot, 'src');

function sourceFiles(root) {
  const files = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const file = join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...sourceFiles(file));
    } else if (/\.(ts|tsx)$/.test(file) && !file.includes('/generated/transport/')) {
      files.push(file);
    }
  }
  return files;
}

function relativeSource(file) {
  return relative(sourceRoot, file).replaceAll('\\', '/');
}

function isTransportBoundary(file) {
  const path = relativeSource(file);
  return path === 'shared/api/transport.ts'
    || path.startsWith('app/mock/')
    || /^(features\/[^/]+\/(types|adapter)\.ts|features\/[^/]+\/api(?:\/.*)?\.ts)$/.test(path);
}

function isViewModelFile(file) {
  const path = relativeSource(file);
  return /^(features\/[^/]+\/(types|adapter)\.ts)$/.test(path) || path.startsWith('app/mock/');
}

const violations = [];
let generatedImports = 0;
let sourceCount = 0;
for (const file of sourceFiles(sourceRoot)) {
  sourceCount += 1;
  const content = readFileSync(file, 'utf8');
  const path = relativeSource(file);

  if (/(?:@|\.\.?)[/]shared\/types(?:['"]|\/)/.test(content)
    || /shared\/api\/transportTypes/.test(content)) {
    violations.push(`${path}: legacy shared type authority import`);
  }

  if (/(?:@|\.\.?)[/]features\//.test(content) && path.startsWith('shared/')) {
    violations.push(`${path}: shared code must not import feature-owned types`);
  }

  if (/(?:@|\.\.?)[/]features\//.test(content) && path.startsWith('design-system/')) {
    violations.push(`${path}: design-system must not import product feature types`);
  }

  for (const match of content.matchAll(/from\s+['"]([^'"]*generated\/transport[^'"]*)['"]/g)) {
    generatedImports += 1;
    if (path.includes('/pages/') || /Page\.(ts|tsx)$/.test(path)) {
      violations.push(`${path}: page consumes generated transport directly; use its feature API/view model`);
    }
  }

  if (!isViewModelFile(file)) {
    for (const match of content.matchAll(/(?:export\s+)?(?:type|interface)\s+([A-Za-z0-9_]*(?:Request|Response|Payload|DTO|Dto))\b/g)) {
      violations.push(`${path}: hand-written transport-shaped type ${match[1]} outside a feature view-model/mock boundary`);
    }
  }
}

const legacySharedTypes = resolve(sourceRoot, 'shared/types');
if (existsSync(legacySharedTypes) && readdirSync(legacySharedTypes).length > 0) {
  violations.push('src/shared/types: legacy shared type directory still tracked');
}

if (violations.length > 0) {
  console.error('type-authority check failed:');
  for (const violation of violations) console.error(`- ${violation}`);
  process.exit(1);
}

console.log(`type-authority: checked ${sourceCount} source files; ${generatedImports} generated transport imports remain at API/adapter/mock boundaries`);
