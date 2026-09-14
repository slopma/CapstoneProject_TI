import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxyTarget = env.VITE_API_PROXY_TARGET

  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_DEV_PORT || 5173),
      ...(apiProxyTarget
        ? {
            proxy: {
              '/api': {
                target: apiProxyTarget,
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, ''),
              },
            },
          }
        : {}),
    },
  }
})