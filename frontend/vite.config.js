import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const apiProxyTarget = process.env.VITE_PROXY_TARGET || "http://backend:8000";
const vncProxyTarget = process.env.VITE_VNC_PROXY_TARGET || "http://backend:6080";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: ["localhost", "127.0.0.1", "host.docker.internal"],
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
        ws: true,
      },
      "/vnc": {
        target: vncProxyTarget,
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/vnc/, ""),
      },
      "/websockify": {
        target: vncProxyTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
