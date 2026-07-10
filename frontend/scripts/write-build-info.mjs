import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(scriptDir, '..')
const repoRoot = resolve(frontendRoot, '..')
const targetPath = resolve(frontendRoot, 'public', 'build-info.json')

function readGitValue(args) {
  try {
    const value = execFileSync('git', args, {
      cwd: repoRoot,
      encoding: 'utf-8',
    }).trim()
    return value || null
  } catch {
    return null
  }
}

function readExistingInfo() {
  if (!existsSync(targetPath)) {
    return { short_commit: null, committed_at: null }
  }
  try {
    const payload = JSON.parse(readFileSync(targetPath, 'utf-8'))
    return {
      short_commit: typeof payload.short_commit === 'string' ? payload.short_commit.trim() || null : null,
      committed_at: typeof payload.committed_at === 'string' ? payload.committed_at.trim() || null : null,
    }
  } catch {
    return { short_commit: null, committed_at: null }
  }
}

const existing = readExistingInfo()
const envCommit = process.env.OPENSCIENCE_BUILD_COMMIT?.trim()
  || process.env.VITE_OPENSCIENCE_BUILD_COMMIT?.trim()
  || process.env.AINRF_BUILD_COMMIT?.trim()
  || process.env.VITE_AINRF_BUILD_COMMIT?.trim()
  || null
const envCommittedAt = process.env.OPENSCIENCE_BUILD_COMMITTED_AT?.trim()
  || process.env.VITE_OPENSCIENCE_BUILD_COMMITTED_AT?.trim()
  || process.env.AINRF_BUILD_COMMITTED_AT?.trim()
  || process.env.VITE_AINRF_BUILD_COMMITTED_AT?.trim()
  || null

const payload = {
  short_commit: (envCommit ? envCommit.slice(0, 6) : null) || readGitValue(['rev-parse', '--short=6', 'HEAD']) || existing.short_commit,
  committed_at: envCommittedAt || readGitValue(['show', '-s', '--format=%cd', '--date=format:%Y%m%d-%H%M', 'HEAD']) || existing.committed_at,
}

mkdirSync(dirname(targetPath), { recursive: true })
writeFileSync(targetPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf-8')
