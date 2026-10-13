import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import packageInfo from './package.json' with { type: 'json' }

export default defineConfig({
  base: './',
  define: { __APP_VERSION__: JSON.stringify(packageInfo.version) },
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
  },
})
