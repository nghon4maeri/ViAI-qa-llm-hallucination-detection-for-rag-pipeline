import { describe, it, expect, afterEach, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import Page from './+page.svelte';

describe('+page.svelte', () => {
	let app: ReturnType<typeof mount> | undefined;

	afterEach(() => {
		if (app) unmount(app);
		vi.unstubAllGlobals();
		document.body.innerHTML = '';
	});

	it('renders the app shell with the RAG check as the default tab', () => {
		// No backend in unit tests: every API call fails and the page must still render
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
		app = mount(Page, { target: document.body });
		flushSync();

		expect(document.querySelector('h1')?.textContent).toBe('ViAI-QA');
		const current = document.querySelector('nav [aria-current="page"]');
		expect(current?.textContent?.trim()).toBe('Kiểm tra RAG');
		expect(document.body.textContent).toContain('Câu hỏi của người dùng');
	});
});
