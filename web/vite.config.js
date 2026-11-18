// Vite-Build: vier Seiten (Start, App, Download, Admin). Alles selbst gehostet, keine data:-URLs (strenge CSP).
import { defineConfig } from 'vite';
export default defineConfig({
  base: '/',
  build: {
    outDir: 'dist', emptyOutDir: true, sourcemap: false, assetsInlineLimit: 0, modulePreload: { polyfill: false },
    rollupOptions: { input: { index: 'index.html', app: 'app.html', d: 'd.html', admin: 'admin.html' } },
  },
});
