import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 18765,
    strictPort: true,
    proxy: {
      "/projects": "http://127.0.0.1:8765",
      "/health": "http://127.0.0.1:8765",
    },
  },
  test: {
    environment: "node",
  },
});
