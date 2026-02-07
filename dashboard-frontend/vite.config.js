import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import seoPrerender from './vite-plugin-seo-prerender.js'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), seoPrerender()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
