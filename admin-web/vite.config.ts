import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/advisor": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000"
    }
  }
});
