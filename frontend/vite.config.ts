import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  envDir: path.resolve(__dirname, "../backend"),
  base: "/dashboard/",
  build: {
    outDir: path.resolve(__dirname, "../backend/app/static/react"),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/billing": "http://127.0.0.1:8000",
      "/live": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
