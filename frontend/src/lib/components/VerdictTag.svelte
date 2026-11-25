<!-- frontend/src/lib/components/VerdictTag.svelte -->
<script lang="ts">
    import { labelMeta, TONE_DOT, TONE_TEXT } from '$lib/labels';

    export let label: string | null | undefined;
    export let long = false;

    $: meta = labelMeta(label);
</script>

<span class="inline-flex items-center gap-2 text-[13px] font-medium {TONE_TEXT[meta.tone]}">
    <span class="size-2 rounded-full {TONE_DOT[meta.tone]}" aria-hidden="true"></span>
    {long ? meta.long : meta.short}
</span>
