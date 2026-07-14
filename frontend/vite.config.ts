import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/static/react/",
  plugins: [tailwindcss(), react()],
  build: {
    outDir: resolve(__dirname, "../core/static/react"),
    assetsDir: "assets",
    emptyOutDir: true,
    // Django collectstatic ignores dot-directories by default; keep the manifest publishable.
    manifest: "manifest.json",
    rollupOptions: {
      input: resolve(__dirname, "index.html"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    origin: "http://127.0.0.1:5173",
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
