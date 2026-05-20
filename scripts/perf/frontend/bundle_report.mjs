#!/usr/bin/env node
/**
 * Bundle report script — builds the frontend with the visualizer plugin
 * and scans output chunks for size anomalies.
 */
import { execSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync, brotliCompressSync } from 'node:zlib';

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = join(__dirname, '..', '..', '..', 'frontend');
const REPO_ROOT = join(__dirname, '..', '..', '..');
const REPORT_DIR = join(REPO_ROOT, '.cache', 'perf-report', new Date().toISOString().slice(0, 10));
const CHUNK_WARN_KB = 500;

function run(cmd, cwd = FRONTEND_DIR) {
    console.log(`> ${cmd}`);
    execSync(cmd, { cwd, encoding: 'utf-8', stdio: 'inherit' });
}

// Step 1: Build with visualizer enabled
console.log('Building frontend with bundle analyzer...');
run('VITE_BUNDLE_ANALYZE=true npx vite build');

// Move the treemap to the report dir
const treemapSrc = join(FRONTEND_DIR, '.cache', 'perf-report', 'bundle-treemap.html');
const treemapDst = join(REPORT_DIR, 'bundle-treemap.html');
mkdirSync(REPORT_DIR, { recursive: true });
try {
    const treemapHtml = readFileSync(treemapSrc, 'utf-8');
    writeFileSync(treemapDst, treemapHtml);
    console.log(`Treemap written to ${treemapDst}`);
} catch {
    console.warn('Warning: treemap HTML not found at expected path.');
}

// Step 2: Collect chunk stats
const distDir = join(FRONTEND_DIR, 'dist');

function collectStats(dir) {
    const chunks = [];
    const entries = readdirSync(dir, { recursive: true, withFileTypes: true });
    for (const entry of entries) {
        const fp = join(entry.parentPath || entry.path, entry.name);
        if (entry.isFile() && (entry.name.endsWith('.js') || entry.name.endsWith('.css'))) {
            const raw = readFileSync(fp);
            chunks.push({
                file: fp.replace(distDir + '/', ''),
                rawBytes: raw.length,
                gzipBytes: gzipSync(raw).length,
                brotliBytes: brotliCompressSync(raw).length,
            });
        }
    }
    return chunks;
}

const chunks = collectStats(distDir);
chunks.sort((a, b) => b.rawBytes - a.rawBytes);

// Step 3: Scan for anomalies
const warnings = [];
for (const c of chunks) {
    if (c.gzipBytes > CHUNK_WARN_KB * 1024) {
        warnings.push(`LARGE CHUNK: ${c.file} — ${(c.gzipBytes / 1024).toFixed(1)}KB gzip`);
    }
}

// Simple duplicate detection
const filenames = chunks.map(c => c.file.split('/').pop() || c.file);
for (let i = 0; i < filenames.length; i++) {
    for (let j = i + 1; j < filenames.length; j++) {
        if (filenames[i] === filenames[j]) {
            warnings.push(`DUPLICATE MODULE: ${chunks[i].file} and ${chunks[j].file} may be the same module in different chunks`);
        }
    }
}

const statsPath = join(REPORT_DIR, 'bundle-stats.json');
writeFileSync(statsPath, JSON.stringify({ chunks, warnings }, null, 2));

if (warnings.length > 0) {
    console.log('\n=== Bundle Warnings ===');
    for (const w of warnings) console.log(`  ⚠  ${w}`);
} else {
    console.log('\nNo bundle size warnings.');
}

console.log(`\nBundle stats written to ${statsPath}`);
