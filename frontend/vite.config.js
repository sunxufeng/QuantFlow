import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 注入前端构建号：部署脚本会设置 QF_BUILD_ID，并把同一值写入 dist/version.json，
// 供 App.jsx 看门狗比对，发现 CDN/浏览器缓存了旧 bundle 时强制刷新。
// 本地直接构建（无 QF_BUILD_ID）则回退到构建时刻时间戳，不影响运行。
const buildId = process.env.QF_BUILD_ID || new Date().toISOString()

export default defineConfig({
  plugins: [react()],
  define: {
    __QF_BUILD_ID__: JSON.stringify(buildId),
  },
  build: {
    // 产物放到默认 assets/ 目录，文件名带 Vite 内容哈希（如 index-DcndtQGp.js），
    // 自带缓存破坏能力（内容一变文件名就变），不再使用「构建号路径隔离」。
    assetsDir: 'assets',
    chunkSizeWarningLimit: 2000,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
