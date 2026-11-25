<!-- services/web/src/lib/components/HalluResult.svelte -->
<script lang="ts">
    import type { AuditResponse } from '$lib/api/api';
    import { RotateCcw, Copy, Check } from 'lucide-svelte';
    import { fly } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import { createEventDispatcher } from 'svelte';
    import { labelMeta, pct, TONE_TEXT } from '$lib/labels';
    import VerdictTag from './VerdictTag.svelte';
    import Breakdown from './Breakdown.svelte';
    import FeedbackPanel from './FeedbackPanel.svelte';

    export let result: AuditResponse;
    const dispatch = createEventDispatcher();

    let copiedReport = false;

    async function copyBugReport() {
        const b = result.breakdown;
        const md =
`### ViAI-QA audit ${result.id}
- Kết luận: ${labelMeta(result.label).long} (tin cậy ${pct(result.confidence, 1)})
- Thời gian: ${result.latency_ms ? result.latency_ms.toFixed(0) + ' ms' : '—'}
- Tài liệu nguồn:
> ${result.context}
- Câu hỏi:
> ${result.prompt}
- Câu trả lời:
> ${result.response}
- NLI: suy ra ${pct(b?.p_entailment)}, mâu thuẫn ${pct(b?.p_contradiction)}
- Thực thể: trùng ${pct(b?.entity_overlap_ratio)}, mới ${b?.new_entity_count ?? '—'}
`;
        try {
            await navigator.clipboard.writeText(md);
            copiedReport = true;
            setTimeout(() => (copiedReport = false), 2500);
        } catch (e) {
            console.error('Clipboard copy error', e);
        }
    }

    $: meta = labelMeta(result.label);
</script>

<article in:fly={{ y: 8, duration: 320, easing: quintOut }} class="space-y-6">
    <header class="flex flex-wrap items-end justify-between gap-6 rounded-xl border border-line bg-card px-6 py-5 shadow-[var(--shadow-sm)]">
        <div class="space-y-2">
            <VerdictTag label={result.label} long />
            <p class="max-w-xl text-[15px] leading-7">{result.response}</p>
        </div>
        <div>
            <div class="text-[13px] text-ink-2">Độ tin cậy</div>
            <div class="mt-1 text-[32px] leading-none font-medium tabular-nums {TONE_TEXT[meta.tone]}">{pct(result.confidence, 1)}</div>
        </div>
    </header>

    <section class="rounded-xl border border-line bg-card p-6">
        <h3 class="mb-4 text-sm font-medium">Vì sao mô hình kết luận như vậy</h3>
        <Breakdown breakdown={result.breakdown} />
    </section>

    <FeedbackPanel {result} />

    <footer class="flex flex-wrap items-center justify-between gap-3 text-xs text-ink-3">
        <span class="font-mono">
            {[result.id.slice(0, 8), result.model_version, result.latency_ms ? `${result.latency_ms.toFixed(0)} ms` : null].filter(Boolean).join(' · ')}
        </span>
        <div class="flex gap-2">
            <button
                type="button"
                on:click={copyBugReport}
                title="Báo cáo Markdown để dán vào Jira, Slack hoặc GitHub"
                class="inline-flex h-8 items-center gap-2 rounded-lg border border-line-strong bg-card px-3 text-[13px] text-ink transition-colors duration-150 hover:bg-raised"
            >
                {#if copiedReport}
                    <Check size={16} strokeWidth={1.5} class="text-ok" /> Đã sao chép
                {:else}
                    <Copy size={16} strokeWidth={1.5} /> Sao chép báo cáo
                {/if}
            </button>
            <button
                type="button"
                on:click={() => dispatch('reset')}
                class="inline-flex h-8 items-center gap-2 rounded-lg border border-line-strong bg-card px-3 text-[13px] text-ink transition-colors duration-150 hover:bg-raised"
            >
                <RotateCcw size={16} strokeWidth={1.5} /> Kiểm tra câu khác
            </button>
        </div>
    </footer>
</article>
