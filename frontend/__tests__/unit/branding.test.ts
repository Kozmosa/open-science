import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('OpenScience branding', () => {
  it('uses the OpenScience brand in the static page title', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf-8');

    expect(html).toContain('<title>OpenScience 学术系统</title>');
    expect(html).not.toMatch(/<title>[^<]*AINRF/i);
    expect(html).toContain('data-osci-theme="light"');
    expect(html).toContain('href="/openscience-mark.svg"');
    expect(html).not.toContain('fonts.googleapis.com');
    expect(html).toContain('<meta name="description"');
    expect(html).toContain('name="robots" content="noindex,nofollow,noarchive"');
    expect(html.match(/name="theme-color"/g)).toHaveLength(2);
  });

  it('publishes private crawler and LLM guidance with the static frontend', () => {
    const robots = readFileSync(resolve(process.cwd(), 'public/robots.txt'), 'utf-8');
    const llms = readFileSync(resolve(process.cwd(), 'public/llms.txt'), 'utf-8');

    expect(robots).toBe('User-agent: *\nDisallow: /\n');
    expect(llms).toContain('private, authenticated research control plane');
    expect(llms).toContain('Do not crawl authenticated routes');
  });

  it('pins the four offline Noto Sans Latin weights', () => {
    const expected = new Map([
      ['400', '09aee8065d25508f23a4c3d92cd777ac869c52d93fd868a88f025d888a7937d6'],
      ['500', '1d35aaecc5c7a375d87c12787e1e4c5d6a695315b757e1e18a479d1a2f84e973'],
      ['600', '79e274470d1c5a0118eb325e2ea6f2eb2a449336d7fde1a4f20a2f32fe1119ed'],
      ['700', 'e77bfe1db912f687b0319b60de158cfada67f89c8ee4f8e2bd6020f970accbfb'],
    ]);
    for (const [weight, hash] of expected) {
      const file = readFileSync(resolve(
        process.cwd(),
        `node_modules/@fontsource/noto-sans/files/noto-sans-latin-${weight}-normal.woff2`,
      ));
      expect(createHash('sha256').update(file).digest('hex')).toBe(hash);
    }
  });
});
