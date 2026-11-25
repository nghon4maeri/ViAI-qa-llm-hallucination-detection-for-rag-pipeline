// frontend/vite.config.ts
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
    plugins: [
        tailwindcss(), 
        sveltekit()
    ],
    server: {
        host: true,
        port: 5173,
        strictPort: true,
        watch: {
            usePolling: true
        }
    },
    // jsdom tests mount components, so Svelte must resolve to its browser build there (not in the app build)
    resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
    test: {
        environment: 'jsdom',
        globals: true,
        include: ['src/**/*.{test,spec}.{js,ts}']
    }
});