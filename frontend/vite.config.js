import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // API key stays server-side in the dev server; it is never sent to the browser
        headers: process.env.API_KEY ? { 'X-API-Key': process.env.API_KEY } : {},
      }
    }
  }
})
