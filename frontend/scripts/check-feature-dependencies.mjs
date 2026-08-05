import { readdirSync, readFileSync } from 'node:fs';
import { dirname, extname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIRECTORY = dirname(fileURLToPath(import.meta.url));
const DEFAULT_SOURCE_ROOT = resolve(SCRIPT_DIRECTORY, '../src');
const SOURCE_EXTENSIONS = new Set(['.js', '.jsx', '.ts', '.tsx']);

const ALLOWED_FEATURE_EDGES = new Map([
  ['environments -> domain', 'environment API delegates to the domain projection Interface'],
  ['overview -> auth', 'overview reads the authenticated user Interface'],
  ['overview -> domain', 'overview renders the domain overview projection Interface'],
  ['projects -> auth', 'projects reads the authenticated user Interface'],
  ['projects -> domain', 'projects consumes project and workspace projection Interfaces'],
  ['projects -> tasks', 'projects consumes task graph and task-creation Interfaces'],
  ['resources -> auth', 'resources reads the authenticated user Interface'],
  ['resources -> tasks', 'resources consumes the task usage projection Interface'],
  ['runs -> projects', 'runs consumes project usage projection data'],
  ['runs -> tasks', 'runs consumes task history and presentation Interfaces'],
  ['settings -> auth', 'settings consumes account and collaborator Interfaces'],
  ['settings -> domain', 'settings consumes domain workspace and collaborator projections'],
  ['settings -> environments', 'settings composes the public environment selector Interface'],
  ['tasks -> auth', 'tasks reads the authenticated user Interface'],
  ['tasks -> domain', 'tasks consumes project, workspace, and capability projections'],
  ['tasks -> settings', 'tasks consumes the public skills/settings Interface'],
  ['terminal -> environments', 'terminal consumes the public environment selection Interface'],
  ['terminal -> settings', 'terminal consumes the public terminal settings Interface'],
  ['timeline -> domain', 'timeline consumes the public project projection Interface'],
  ['timeline -> tasks', 'timeline consumes the public task projection Interface'],
  ['workspaces -> auth', 'workspaces reads the authenticated user Interface'],
  ['workspaces -> domain', 'workspaces consumes workspace and project projection Interfaces'],
  ['workspaces -> environments', 'workspaces consumes the public environment selection Interface'],
  ['workspaces -> settings', 'workspaces consumes the public editor settings Interface'],
]);

function walk(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...walk(path));
    } else if (SOURCE_EXTENSIONS.has(extname(path))) {
      files.push(path);
    }
  }
  return files;
}

function relativeSourcePath(sourceRoot, path) {
  return relative(sourceRoot, path).split(sep).join('/');
}

function classifyPath(sourceRoot, path) {
  const relativePath = relativeSourcePath(sourceRoot, path);
  const parts = relativePath.split('/');
  if (parts[0] === 'features' && parts[1]) {
    return { layer: 'feature', name: parts[1] };
  }
  if (parts[0] === 'shared') {
    return { layer: 'shared', name: 'shared' };
  }
  if (parts[0] === 'design-system') {
    return { layer: 'design-system', name: 'design-system' };
  }
  if (parts[0] === 'app' || parts[0] === 'pages' || ['App.tsx', 'main.tsx'].includes(parts[0])) {
    return { layer: 'app', name: 'app' };
  }
  return null;
}

function resolveImportPath(sourceRoot, sourceFile, specifier) {
  if (specifier === '@features' || specifier.startsWith('@features/')) {
    return resolve(sourceRoot, 'features', specifier.slice('@features'.length).replace(/^\/+/, ''));
  }
  if (specifier === '@/features' || specifier.startsWith('@/features/')) {
    return resolve(sourceRoot, specifier.slice(2));
  }
  if (specifier === '@shared' || specifier.startsWith('@shared/')) {
    return resolve(sourceRoot, 'shared', specifier.slice('@shared'.length).replace(/^\/+/, ''));
  }
  if (specifier === '@design-system' || specifier.startsWith('@design-system/')) {
    return resolve(sourceRoot, 'design-system', specifier.slice('@design-system'.length).replace(/^\/+/, ''));
  }
  if (specifier.startsWith('@/')) {
    return resolve(sourceRoot, specifier.slice(2));
  }
  if (specifier.startsWith('.')) {
    return resolve(dirname(sourceFile), specifier);
  }
  return null;
}

function isPublicFeatureBarrel(sourceRoot, path, target) {
  if (target?.layer !== 'feature') return false;
  return resolve(sourceRoot, 'features', target.name) === path;
}

function parseImportReferences(sourceRoot, sourceFile) {
  const sourceText = readFileSync(sourceFile, 'utf8');
  const patterns = [
    { kind: 'static', expression: /\bfrom\s*(['"])([^'"]+)\1/g },
    { kind: 'static', expression: /\bimport\s*(['"])([^'"]+)\1/g },
    { kind: 'dynamic', expression: /\bimport\s*\(\s*(['"])([^'"]+)\1/g },
  ];
  const references = [];
  for (const { kind, expression } of patterns) {
    for (const match of sourceText.matchAll(expression)) {
      const specifier = match[2];
      const targetPath = resolveImportPath(sourceRoot, sourceFile, specifier);
      const target = targetPath ? classifyPath(sourceRoot, targetPath) : null;
      if (target === null) continue;
      const source = classifyPath(sourceRoot, sourceFile);
      if (source === null) continue;
      const mechanism = kind === 'dynamic'
        ? 'dynamic'
        : isPublicFeatureBarrel(sourceRoot, targetPath, target)
          ? 'barrel'
          : specifier.startsWith('@')
            ? 'alias'
            : 'relative';
      const line = sourceText.slice(0, match.index).split('\n').length;
      references.push({
        source,
        target,
        file: relativeSourcePath(sourceRoot, sourceFile),
        line,
        specifier,
        kind,
        mechanism,
        targetPath,
      });
    }
  }
  return references;
}

function featureEdgeKey(source, target) {
  return `${source.name} -> ${target.name}`;
}

function findCycles(features, edges) {
  const graph = new Map(features.map((feature) => [feature, new Set()]));
  for (const edge of edges) graph.get(edge.source.name)?.add(edge.target.name);

  const indexByNode = new Map();
  const lowLinkByNode = new Map();
  const stack = [];
  const onStack = new Set();
  const stronglyConnectedComponents = [];
  let nextIndex = 0;

  function visit(node) {
    indexByNode.set(node, nextIndex);
    lowLinkByNode.set(node, nextIndex);
    nextIndex += 1;
    stack.push(node);
    onStack.add(node);

    for (const next of graph.get(node) ?? []) {
      if (!indexByNode.has(next)) {
        visit(next);
        lowLinkByNode.set(node, Math.min(lowLinkByNode.get(node), lowLinkByNode.get(next)));
      } else if (onStack.has(next)) {
        lowLinkByNode.set(node, Math.min(lowLinkByNode.get(node), indexByNode.get(next)));
      }
    }

    if (lowLinkByNode.get(node) === indexByNode.get(node)) {
      const members = [];
      let member;
      do {
        member = stack.pop();
        onStack.delete(member);
        members.push(member);
      } while (member !== node);
      if (members.length > 1 || graph.get(node)?.has(node)) {
        stronglyConnectedComponents.push(members.sort());
      }
    }
  }

  for (const feature of features) {
    if (!indexByNode.has(feature)) visit(feature);
  }
  return stronglyConnectedComponents;
}

function uniqueEdges(references) {
  const edges = new Map();
  for (const reference of references) {
    if (reference.source.layer !== 'feature' || reference.target.layer !== 'feature') continue;
    if (reference.source.name === reference.target.name) continue;
    const key = featureEdgeKey(reference.source, reference.target);
    if (!edges.has(key)) {
      edges.set(key, {
        source: reference.source,
        target: reference.target,
        key,
        sites: [],
      });
    }
    edges.get(key).sites.push(reference);
  }
  return [...edges.values()].sort((left, right) => left.key.localeCompare(right.key));
}

export function analyzeFeatureDependencies(sourceRoot = DEFAULT_SOURCE_ROOT) {
  const files = walk(sourceRoot);
  const references = files.flatMap((file) => parseImportReferences(sourceRoot, file));
  const featureNames = [...new Set(
    files
      .map((file) => classifyPath(sourceRoot, file))
      .filter((module) => module?.layer === 'feature')
      .map((module) => module.name),
  )].sort();
  const featureEdges = uniqueEdges(references);
  const selfBarrelImports = references.filter((reference) => (
    reference.source.layer === 'feature'
    && reference.target.layer === 'feature'
    && reference.source.name === reference.target.name
    && reference.mechanism === 'barrel'
  ));
  const cycles = findCycles(featureNames, featureEdges);
  const invalidFeatureEdges = featureEdges.filter((edge) => !ALLOWED_FEATURE_EDGES.has(edge.key));
  const layerViolations = references.filter((reference) => (
    (['shared', 'design-system'].includes(reference.source.layer) && reference.target.layer === 'feature')
    || (reference.source.layer === 'feature' && reference.target.layer === 'app')
  ));
  const violations = [
    ...layerViolations.map((reference) => (
      `${reference.source.layer} may not depend on ${reference.target.layer}: ${reference.file}:${reference.line} imports ${reference.specifier}`
    )),
    ...invalidFeatureEdges.flatMap((edge) => edge.sites.map((site) => (
      `feature dependency is not explicitly allowed (${edge.key}): ${site.file}:${site.line} imports ${site.specifier}`
    ))),
    ...selfBarrelImports.map((reference) => (
      `feature may not import its own public barrel: ${reference.file}:${reference.line} imports ${reference.specifier}`
    )),
    ...cycles.map((cycle) => `feature dependency cycle: ${cycle.join(' -> ')}`),
  ];

  return {
    files,
    references,
    featureNames,
    featureEdges,
    allowedFeatureEdges: featureEdges.filter((edge) => ALLOWED_FEATURE_EDGES.has(edge.key)),
    selfBarrelImports,
    cycles,
    violations,
  };
}

function formatReference(reference) {
  const source = `${reference.source.layer}:${reference.source.name}`;
  const target = `${reference.target.layer}:${reference.target.name}`;
  return `${source} -> ${target} [${reference.mechanism}/${reference.kind}] ${reference.file}:${reference.line} ${reference.specifier}`;
}

function printReport(report) {
  console.log(`[feature-dependencies] source files: ${report.files.length}`);
  console.log(`[feature-dependencies] feature graph: ${report.featureNames.length} nodes, ${report.featureEdges.length} edges, ${report.cycles.length} cycles`);
  console.log(`[feature-dependencies] allowed feature-to-feature edges: ${report.allowedFeatureEdges.length}`);
  console.log('[feature-dependencies] complete cross-layer graph:');
  for (const reference of report.references
    .filter((reference) => reference.source.layer !== reference.target.layer)
    .sort((left, right) => `${left.file}:${left.line}`.localeCompare(`${right.file}:${right.line}`))) {
    console.log(`  ${formatReference(reference)}`);
  }
  if (report.selfBarrelImports.length > 0) {
    console.error('[feature-dependencies] self-barrel imports:');
    for (const reference of report.selfBarrelImports) console.error(`  ${formatReference(reference)}`);
  }
  if (report.violations.length > 0) {
    console.error('[feature-dependencies] violations:');
    for (const violation of report.violations) console.error(`  ${violation}`);
    return;
  }
  console.log('[feature-dependencies] PASS');
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const report = analyzeFeatureDependencies();
  printReport(report);
  if (report.violations.length > 0) process.exitCode = 1;
}
