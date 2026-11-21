import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Load VITE_* variables from the project-root .env (shared with the backend).
  envDir: "..",
  server: {
    host: true,
    port: 5173,
  },
});
