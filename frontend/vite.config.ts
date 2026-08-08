import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    clearMocks: true,
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    watch: {
      // bind mounts em Docker Desktop (Windows/Mac) nao emitem inotify;
      // polling garante hot reload dentro do container.
      usePolling: true,
    },
  },
});
