import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { developmentBackendTarget, frontendConfig } from './src/config/frontendConfig'

const backendTarget = developmentBackendTarget(process.env)
const backendWsTarget = backendTarget.replace(/^http/, 'ws')

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    host: frontendConfig.development.host,
    port: frontendConfig.development.frontendPort,
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
