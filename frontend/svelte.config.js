import adapterNode from '@sveltejs/adapter-node';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

let selectedAdapter = adapterNode();

// Auto-detect Vercel environment
if (process.env.VERCEL) {
	try {
		const { default: adapterVercel } = await import('@sveltejs/adapter-vercel');
		selectedAdapter = adapterVercel();
	} catch {
		// Fallback to adapter-node if adapter-vercel is not yet installed
		selectedAdapter = adapterNode();
	}
}

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: { adapter: selectedAdapter }
};

export default config;
