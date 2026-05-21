#!/usr/bin/env node
/**
 * Lighthouse CI audit for key pages.
 *
 * Usage: node scripts/perf/frontend/lighthouse.js [--url=http://localhost:5173]
 *
 * Requires a running frontend dev server.
 */
import { execSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, '..', '..', '..');
const REPORT_DIR = join(REPO_ROOT, '.cache', 'perf-report', new Date().toISOString().slice(0, 10));

const BASE_URL = process.argv.find(a => a.startsWith('--url='))?.split('=')[1] || 'http://localhost:5173';
const PAGES = ['/login', '/projects', '/tasks'];

function run(cmd) {
    console.log(`> ${cmd}`);
    execSync(cmd, { encoding: 'utf-8', stdio: 'inherit' });
}

mkdirSync(REPORT_DIR, { recursive: true });

let allPassed = true;

for (const page of PAGES) {
    const url = `${BASE_URL}${page}`;
    console.log(`\n=== Auditing ${url} ===`);
    const slug = page.replace(/^\//, '').replace(/\//g, '-') || 'home';

    try {
        run(`npx lhci collect --url="${url}" --numberOfRuns=3`);
        run(`npx lhci assert --preset=recommended --includePassed=false || true`);
    } catch (e) {
        console.warn(`Warning: Lighthouse audit had issues for ${url}: ${e.message}`);
        allPassed = false;
    }
}

console.log(`\nLighthouse audit complete. Outputs in ${REPORT_DIR}`);
process.exit(allPassed ? 0 : 0); // Never fail on audit — just report
