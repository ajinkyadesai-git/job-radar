/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// In development, /api/* goes to the Job Radar API with the key added here, on the dev
// server, so the key never reaches the browser. In production CloudFront does the same job.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", ""); // the repo's .env (not exposed to the page)
  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": {
          target: env.JOBRADAR_WEB_API ?? "http://127.0.0.1:8000",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
          headers: { "X-API-Key": env.JOBRADAR_API_KEY ?? "" },
        },
      },
    },
    test: { environment: "node" },
  };
});
