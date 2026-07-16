import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const guardedPaths = [
  'src/features/tasks',
  'src/design-system/primitives',
  'src/components/common/Layout.tsx',
] as const;

const taskTokenContractPaths = [
  'src/pages/TasksPage.tsx',
  'src/features/tasks',
  'src/components/messages',
  'src/design-system/layout/SplitPane.tsx',
] as const;

const tokenDefinitionPaths = [
  'src/design-system/tokens/palette.css',
  'src/design-system/tokens/semantic.css',
  'src/design-system/tokens/component.css',
  'src/design-system/tokens/themes/osci-light.css',
  'src/design-system/tokens/themes/osci-dark.css',
] as const;

const forbiddenStylePattern = /#[0-9A-Fa-f]{3,8}|\bbg-white\b|\btext-gray-|\bbg-blue-|\bbg-red-|\bborder-green-|\bhover:bg-gray-|\btext-blue-|\btext-red-/;

function collectSourceFiles(path: string): string[] {
  const absolutePath = join(process.cwd(), path);
  if (path.endsWith('.tsx') || path.endsWith('.ts')) {
    return [absolutePath];
  }

  return readdirSync(absolutePath, { withFileTypes: true }).flatMap((entry) => {
    const childPath = join(path, entry.name);
    if (entry.isDirectory()) {
      return collectSourceFiles(childPath);
    }
    if (entry.isFile() && /\.(tsx|ts|css)$/.test(entry.name)) {
      return [join(process.cwd(), childPath)];
    }
    return [];
  });
}

describe('semantic frontend styling guard', () => {
  it('keeps task, common layout, and shared UI surfaces on semantic theme tokens', () => {
    const violations = guardedPaths
      .flatMap(collectSourceFiles)
      .flatMap((file) => {
        const content = readFileSync(file, 'utf8');
        return content.split('\n').flatMap((line, index) => {
          if (forbiddenStylePattern.test(line)) {
            return [`${file.replace(`${process.cwd()}/`, '')}:${index + 1}:${line.trim()}`];
          }
          return [];
        });
      });

    expect(violations).toEqual([]);
  });

  it('keeps the Task workspace free of legacy and undeclared runtime tokens', () => {
    const declaredTokens = new Set(tokenDefinitionPaths.flatMap((path) => {
      const content = readFileSync(join(process.cwd(), path), 'utf8');
      return [...content.matchAll(/(--osci-[a-z0-9-]+)\s*:/g)].map((match) => match[1]!);
    }));
    const violations = taskTokenContractPaths
      .flatMap(collectSourceFiles)
      .flatMap((file) => {
        const content = readFileSync(file, 'utf8');
        return content.split('\n').flatMap((line, index) => {
          const legacy = line.match(/var\((--(?!osci-)[a-z0-9-]+)/g) ?? [];
          const unknown = [...line.matchAll(/var\((--osci-[a-z0-9-]+)/g)]
            .map((match) => match[1]!)
            .filter((token) => !declaredTokens.has(token));
          return [...legacy, ...unknown].map((token) => (
            `${file.replace(`${process.cwd()}/`, '')}:${index + 1}:${token}`
          ));
        });
      });

    expect(violations).toEqual([]);
  });
});
