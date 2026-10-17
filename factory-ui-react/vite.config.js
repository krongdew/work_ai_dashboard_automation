import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

// Build the SPA directly into the Flask static dir so Flask serves it.
export default defineConfig({
  plugins: [react()],
  base: '/static/dist/',
  build: {
    outDir: resolve(__dirname, '../factory-ui/static/dist'),
    emptyOutDir: true,
    rollupOptions: {
      // Three.js is loaded from the CDN at runtime via the import map in
      // index.html (keeps the bundle small, no extra npm dependency). Leave the
      // bare 'three' specifiers external so the browser resolves them.
      external: ['three', /^three\//],
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5050',
    },
  },
});
