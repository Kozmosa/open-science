import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const guardedPaths = [
  'src/pages/tasks',
  'src/components/ui',
  'src/components/common/Layout.tsx',
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
});
