import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = process.env.GAOJIAOHUI_BACKEND_URL || 'http://127.0.0.1:8766'

// 开发模式：vite dev (5173) 代理 /proxy 到 FastAPI (8766)
// 生产模式：npm run build -> dist/，由 FastAPI 直接托管，单端口 8766
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/proxy': { target: backend, changeOrigin: true }
    }
  },
  build: { outDir: 'dist', emptyOutDir: true }
})
