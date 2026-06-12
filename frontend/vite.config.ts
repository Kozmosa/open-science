import { execFileSync } from 'node:child_process'
import { resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { visualizer } from 'rollup-plugin-visualizer'
import { sharedAinrfProxyConfig } from './vite.proxy'

// https://vite.dev/config/
const ANALYZE = process.env.VITE_BUNDLE_ANALYZE === 'true'

function readGitValue(args: string[]): string | null {
  try {
    const value = execFileSync('git', args, {
      cwd: resolve(process.cwd(), '..'),
      encoding: 'utf-8',
    }).trim()
    return value || null
  } catch {
    return null
  }
}

function resolveBuildInfo(): { shortCommit: string | null; committedAt: string | null } {
  const envCommit = process.env.AINRF_BUILD_COMMIT?.trim() || process.env.VITE_AINRF_BUILD_COMMIT?.trim() || null
  const envCommittedAt = process.env.AINRF_BUILD_COMMITTED_AT?.trim() || process.env.VITE_AINRF_BUILD_COMMITTED_AT?.trim() || null

  return {
    shortCommit: envCommit ? envCommit.slice(0, 6) : readGitValue(['rev-parse', '--short=6', 'HEAD']),
    committedAt: envCommittedAt || readGitValue(['show', '-s', '--format=%cd', '--date=format:%Y%m%d-%H%M', 'HEAD']),
  }
}

const BUILD_INFO = resolveBuildInfo()

const config = defineConfig({
  define: {
    __AINRF_BUILD_INFO__: JSON.stringify(BUILD_INFO),
  },
  plugins: [react(), tailwindcss(),
    ...(ANALYZE ? [visualizer({
      open: false,
      gzipSize: true,
      brotliSize: true,
      filename: '.cache/perf-report/bundle-treemap.html',
      template: 'treemap',
    })] : []),
  ],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }
          if (id.includes('xterm') || id.includes('@xterm')) {
            return 'terminal-vendor'
          }
          if (
            id.includes('react-router-dom') ||
            id.includes('@tanstack/react-query') ||
            id.includes('/react/') ||
            id.includes('/react-dom/')
          ) {
            return 'app-vendor'
          }
          return 'vendor'
        },
      },
    },
  },
  server: {
    proxy: sharedAinrfProxyConfig,
    host: '0.0.0.0', // 监听所有地址，使开发服务器可被外部访问
    port: 5173, // 可选，指定端口
  },
  preview: {
    proxy: sharedAinrfProxyConfig,
    host: '0.0.0.0', // 使预览服务器也可被外部访问
    port: 4173, // 预览服务器默认端口为4173，可根据需要修改
  }
})

export default config
