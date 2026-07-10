import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { resolve } from 'path'
import { visualizer } from 'rollup-plugin-visualizer'
import { sharedOpenScienceProxyConfig } from './vite.proxy'

// https://vite.dev/config/
const ANALYZE = process.env.VITE_BUNDLE_ANALYZE === 'true'
const FRONTEND_OUT_DIR = process.env.OPENSCIENCE_FRONTEND_OUT_DIR?.trim() || 'dist'

const config = defineConfig({
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
    outDir: FRONTEND_OUT_DIR,
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
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
      '@design-system': resolve(__dirname, './src/design-system'),
      '@features': resolve(__dirname, './src/features'),
      '@shared': resolve(__dirname, './src/shared'),
    },
  },
  server: {
    proxy: sharedOpenScienceProxyConfig,
    host: '0.0.0.0', // 监听所有地址，使开发服务器可被外部访问
    port: 5173, // 可选，指定端口
  },
  preview: {
    proxy: sharedOpenScienceProxyConfig,
    host: '0.0.0.0', // 使预览服务器也可被外部访问
    port: 4173, // 预览服务器默认端口为4173，可根据需要修改
  }
})

export default config
