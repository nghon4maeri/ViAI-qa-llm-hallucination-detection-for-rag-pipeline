<!-- applications/web/src/lib/components/Header.svelte -->
<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchProjects, type Project } from '$lib/api/api';
	import { createEventDispatcher } from 'svelte';

	export let selectedProjectId: string = '';
	const dispatch = createEventDispatcher();

	let projects: Project[] = [];

	onMount(async () => {
		try {
			projects = await fetchProjects();
			if (projects.length > 0 && !selectedProjectId) {
				const defaultP = projects.find((p) => p.is_default) || projects[0];
				selectedProjectId = defaultP.id;
				dispatch('projectChange', selectedProjectId);
			}
		} catch (err) {
			console.warn('Could not load projects:', err);
		}
	});

	function handleSelect(e: Event) {
		const target = e.target as HTMLSelectElement;
		selectedProjectId = target.value;
		dispatch('projectChange', selectedProjectId);
	}
</script>

<header
	class="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-line bg-card px-4 sm:px-6"
>
	<div class="flex items-baseline gap-3">
		<h1 class="whitespace-nowrap text-base font-semibold leading-none">ViAI-QA</h1>
		<p class="hidden text-[13px] text-ink-2 sm:block">Kiểm định câu trả lời RAG y tế</p>
	</div>

	<label class="flex items-center gap-2 text-[13px]">
		<span class="hidden text-ink-2 sm:inline">Dự án</span>
		{#if projects.length > 0}
			<select
				bind:value={selectedProjectId}
				on:change={handleSelect}
				class="h-8 max-w-[180px] rounded-lg border border-line-strong bg-card px-2 text-[13px] focus:border-accent focus:outline-none sm:max-w-none"
			>
				{#each projects as proj (proj.id)}
					<option value={proj.id}>{proj.name}{proj.is_default ? ' (mặc định)' : ''}</option>
				{/each}
			</select>
		{:else}
			<span>Mặc định</span>
		{/if}
	</label>
</header>
