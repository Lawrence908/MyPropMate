import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, API calls go to the running container (host port 8139).
// Override with VITE_API_TARGET when the API runs elsewhere.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': process.env.VITE_API_TARGET ?? 'http://localhost:8139',
    },
  },
})
