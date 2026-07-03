import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendTarget = process.env.DXM_BACKEND_URL || `http://127.0.0.1:${process.env.DXM_BACKEND_PORT || '8000'}`
const backendWsTarget = backendTarget.replace(/^http/, 'ws')

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: backendWsTarget,
        ws: true,
      },
    },
  },
})
