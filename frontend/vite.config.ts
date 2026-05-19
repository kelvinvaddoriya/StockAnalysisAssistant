import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // .env lives in the monorepo root, one level above frontend/
  envDir: '..',
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8888',
        changeOrigin: true,
      },
    },
  },
  optimizeDeps: {
    include: [
      '@thesysai/genui-sdk',
      '@crayonai/react-ui',
      'recharts',
      'react-syntax-highlighter',
      'lucide-react',
      'lodash-es',
      'react-markdown',
    ],
  },
})
