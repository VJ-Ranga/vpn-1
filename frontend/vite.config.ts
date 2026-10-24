import { defineConfig } from 'vitest/config'; import react from '@vitejs/plugin-react';
export default defineConfig({ plugins: [react()], server: { host: '127.0.0.1', port: 5173, proxy: { '/api': `http://127.0.0.1:${process.env.VPN_UI_PORT || '8766'}` } }, test: { environment: 'jsdom' } });
