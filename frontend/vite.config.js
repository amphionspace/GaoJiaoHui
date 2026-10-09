import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发模式：vite dev (5173) 代理 /proxy 到 FastAPI (8766)
// 生产模式：npm run build -> dist/，由 FastAPI 直接托管，单端口 8766
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/proxy': { target: 'http://127.0.0.1:8766', changeOrigin: true }
    }
  },
  build: { outDir: 'dist', emptyOutDir: true }
})
