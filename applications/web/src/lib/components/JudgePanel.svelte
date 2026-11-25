<!-- applications/web/src/lib/components/JudgePanel.svelte -->
<!-- Tier 2: a Claude agent re-checks the sentences Tier 1 was unsure of, with a visible tool-call trail -->
<script lang="ts">
    import { Loader2 } from 'lucide-svelte';
    import type { AuditResponse, ClaimVerdict } from '$lib/api/api';
    import { requestJudge } from '$lib/api/api';
    import { labelMeta, pct } from '$lib/labels';
    import VerdictTag from './VerdictTag.svelte';

    export let result: AuditResponse;
    export let claims: ClaimVerdict[];

    let isRunning = false;
    let error = '';

    $: judge = result.judge;
    $: disagreements = judge?.claims.filter((c) => !c.agrees_with_tier1) ?? [];

    const STATUS: Record<string, string> = {
        completed: 'Agent đã kiểm tra xong',
        refused: 'Agent từ chối yêu cầu này, kết quả Tier 1 được giữ',
        incomplete: 'Agent chưa kết luận đủ, kết quả Tier 1 được giữ',
    };

    async function run() {
        isRunning = true;
        error = '';
        try {
            result = await requestJudge(result.id);
        } catch (e: any) {
            error = e.message;
        } finally {
            isRunning = false;
        }
    }

    const summarize = (input: Record<string, unknown>) =>
        typeof input.context_index === 'number' ? `tài liệu [${input.context_index + 1}]` : '';
</script>

<section class="space-y-4 rounded-xl border border-line bg-card p-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="space-y-1">
            <h3 class="text-sm font-medium">Thẩm định sâu bằng agent</h3>
            <p class="max-w-xl text-[13px] text-ink-2">
                Một agent Claude kiểm tra lại các câu mô hình chưa chắc, bằng chính bộ phát hiện và công cụ so số liều
            </p>
        </div>
        {#if !judge}
            <button
                type="button"
                on:click={run}
                disabled={isRunning}
                class="inline-flex h-9 items-center gap-2 rounded-lg border border-line-strong bg-card px-3 text-[13px] transition-colors duration-150 hover:bg-raised disabled:opacity-50"
            >
                {#if isRunning}<Loader2 size={16} strokeWidth={1.5} class="animate-spin" /> Agent đang kiểm tra{:else}Nhờ agent kiểm tra lại{/if}
            </button>
        {/if}
    </div>

    {#if error}
        <p class="text-[13px] text-bad">{error}</p>
    {/if}

    {#if judge}
        <div class="space-y-4 border-t border-line pt-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
                <span class="text-[13px] {judge.status === 'completed' ? 'text-ink' : 'text-warn'}">{STATUS[judge.status]}</span>
                {#if judge.status === 'completed'}
                    <span class="flex items-center gap-4 text-[13px]">
                        <VerdictTag label={judge.label} />
                        <span class="text-ink-2">bám nguồn <span class="font-mono tabular-nums text-ink">{pct(judge.faithfulness)}</span></span>
                    </span>
                {/if}
            </div>

            {#if judge.explanation}
                <p class="text-[14px] leading-6">{judge.explanation}</p>
            {/if}

            {#if judge.status === 'completed'}
                {#if disagreements.length}
                    <ul class="space-y-3">
                        {#each disagreements as c}
                            <li class="rounded-lg bg-raised px-4 py-3 text-[13px] leading-6">
                                <div class="flex flex-wrap items-center gap-2">
                                    <span class="text-ink-2">Câu {c.index + 1}:</span>
                                    <span class="text-ink-3 line-through">{labelMeta(claims[c.index]?.label).short}</span>
                                    <span aria-hidden="true" class="text-ink-3">→</span>
                                    <VerdictTag label={c.label} />
                                    {#if c.evidence_index != null}<span class="font-mono text-xs text-ink-3">[{c.evidence_index + 1}]</span>{/if}
                                </div>
                                <p class="mt-1">{c.reason}</p>
                            </li>
                        {/each}
                    </ul>
                {:else}
                    <p class="text-[13px] text-ink-2">Agent đồng ý với mọi kết luận của mô hình</p>
                {/if}
            {/if}

            {#if judge.tool_calls.length}
                <details>
                    <summary class="cursor-pointer text-[13px] text-ink-2 hover:text-ink">
                        {judge.tool_calls.length} lần gọi công cụ
                    </summary>
                    <ol class="mt-3 space-y-2 border-l border-line pl-4">
                        {#each judge.tool_calls as call}
                            <li class="text-[13px]">
                                <span class="font-mono text-xs">{call.name}</span>
                                <span class="text-ink-2">{summarize(call.input)}</span>
                                <span class="font-mono text-xs text-ink-3 tabular-nums">· {call.latency_ms.toFixed(0)} ms</span>
                            </li>
                        {/each}
                    </ol>
                </details>
            {/if}

            <p class="font-mono text-xs text-ink-3 tabular-nums">
                {judge.model} · {judge.input_tokens} token vào · {judge.output_tokens} token ra · {(judge.latency_ms / 1000).toFixed(1)} s
            </p>
        </div>
    {/if}
</section>
