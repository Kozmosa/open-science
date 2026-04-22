import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { sharedAinrfProxyConfig } from './vite.proxy'

// https://vite.dev/config/
const config = defineConfig({
  plugins: [react(), tailwindcss()],
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
