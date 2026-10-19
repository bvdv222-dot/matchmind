import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: the API runs on :8000 (python -m api); Vite proxies REST and the live feed to it
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
