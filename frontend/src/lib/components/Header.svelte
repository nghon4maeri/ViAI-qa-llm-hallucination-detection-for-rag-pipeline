<!-- frontend/src/lib/components/Header.svelte -->
<script lang="ts">
    import { onMount } from 'svelte';
    import { Bot, Sparkles, FolderGit2, CheckCircle2 } from 'lucide-svelte';
    import { fetchProjects, type Project } from '$lib/api/api';
    import { createEventDispatcher } from 'svelte';

    export let selectedProjectId: string = '';
    const dispatch = createEventDispatcher();

    let projects: Project[] = [];

    onMount(async () => {
        try {
            projects = await fetchProjects();
            if (projects.length > 0 && !selectedProjectId) {
                const defaultP = projects.find(p => p.is_default) || projects[0];
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

<header class="flex items-center justify-between px-6 py-4 border-b border-white/5 bg-slate-950/40 backdrop-blur-md relative z-30">
    <!-- Brand -->
    <div class="flex items-center gap-3">
        <div class="relative p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 shadow-[0_0_15px_rgba(99,102,241,0.2)]">
            <Bot size={24} class="text-indigo-400" />
            <Sparkles size={10} class="absolute -top-0.5 -right-0.5 text-pink-400 animate-pulse" />
        </div>
        <div>
            <div class="flex items-center gap-2">
                <h1 class="text-base font-bold tracking-tight text-white">
                    ViAI-<span class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-pink-400">QA</span>
                </h1>
                <span class="text-[10px] font-mono font-medium px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                    <CheckCircle2 size={10} /> Online
                </span>
            </div>
            <p class="text-[10px] text-slate-400">Vietnamese AI Response Quality Assurance Workspace</p>
        </div>
    </div>

    <!-- Workspace Selector -->
    <div class="flex items-center gap-3">
        <div class="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-white/[0.03] border border-white/10 text-xs text-slate-300">
            <FolderGit2 size={14} class="text-indigo-400" />
            <span class="text-slate-500">Workspace:</span>
            {#if projects.length > 0}
                <select 
                    bind:value={selectedProjectId}
                    on:change={handleSelect}
                    class="bg-transparent text-slate-200 font-medium focus:outline-none cursor-pointer pr-2"
                >
                    {#each projects as proj}
                        <option value={proj.id} class="bg-slate-900 text-slate-200">
                            {proj.name} {proj.is_default ? '(Mặc định)' : ''}
                        </option>
                    {/each}
                </select>
            {:else}
                <span class="font-medium text-slate-300">Default Workspace</span>
            {/if}
        </div>
    </div>
</header>
