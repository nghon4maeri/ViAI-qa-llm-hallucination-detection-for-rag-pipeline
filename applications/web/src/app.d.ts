/// <reference types="@sveltejs/kit" />

declare module '*.svelte' {
	import { SvelteComponentTyped } from 'svelte';

	export default class Component<
		Props = Record<string, unknown>,
		Events = Record<string, unknown>,
		Slots = Record<string, unknown>
	> extends SvelteComponentTyped<Props, Events, Slots> {}
}
