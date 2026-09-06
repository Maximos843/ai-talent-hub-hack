import path from 'path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// SPA рабочего места рекрутера. Собирается в ../static/app и раздаётся FastAPI,
// поэтому base совпадает с точкой монтирования StaticFiles.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/static/app/',
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      // secure:false — у dev-сервера self-signed сертификат
      '/api': { target: 'https://localhost:8000', changeOrigin: true, secure: false },
      '/uploads': { target: 'https://localhost:8000', changeOrigin: true, secure: false },
    },
  },
})
