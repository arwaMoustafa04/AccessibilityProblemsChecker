import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server forwards /api/* to the backend, so the browser never makes a
// cross-origin request. Point it at the deployed system with e.g.
//   API_PROXY_TARGET=http://3.15.117.84/system npm run dev
const API_PROXY_TARGET = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000'

// base: './' lets the built files be served from any path (e.g. /system/ui/ later).
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    proxy: {
      '/api': {
        target: API_PROXY_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
