import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('OpenScience branding', () => {
  it('uses the OpenScience brand in the static page title', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf-8');

    expect(html).toContain('<title>OpenScience 学术系统</title>');
    expect(html).not.toMatch(/<title>[^<]*AINRF/i);
  });
});
