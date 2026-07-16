import { readdir, rm } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(scriptDir, '..')
const sharedDistRoot = resolve(frontendRoot, 'dist')
const configuredOutDir = process.env.OPENSCIENCE_FRONTEND_OUT_DIR?.trim() || 'dist'
const resolvedOutDir = resolve(frontendRoot, configuredOutDir)
const deploymentBundles = new Set(['production', 'staging', 'gpu'])

if (resolvedOutDir === sharedDistRoot) {
  const entries = await readdir(sharedDistRoot, { withFileTypes: true }).catch((error) => {
    if (error?.code === 'ENOENT') {
      return []
    }
    throw error
  })

  for (const entry of entries) {
    if (entry.isDirectory() && deploymentBundles.has(entry.name)) {
      continue
    }
    await rm(resolve(sharedDistRoot, entry.name), { recursive: true, force: true })
  }
}
