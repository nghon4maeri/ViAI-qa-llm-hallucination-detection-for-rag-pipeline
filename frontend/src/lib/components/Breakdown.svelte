<!-- frontend/src/lib/components/Breakdown.svelte -->
<script lang="ts">
    import type { EvaluationBreakdown } from '$lib/api/api';
    import { pct } from '$lib/labels';

    export let breakdown: EvaluationBreakdown | null | undefined;

    $: nli = [
        { name: 'Được suy ra từ nguồn', value: breakdown?.p_entailment, bar: 'bg-ok' },
        { name: 'Trung tính', value: breakdown?.p_neutral, bar: 'bg-ink-3' },
        { name: 'Mâu thuẫn', value: breakdown?.p_contradiction, bar: 'bg-bad' },
    ];
</script>

{#if breakdown}
    <dl class="grid gap-6 sm:grid-cols-3">
        <div class="space-y-3">
            <dt class="text-[13px] text-ink-2">Suy luận NLI</dt>
            {#each nli as row}
                <dd class="space-y-1">
                    <div class="flex justify-between text-[13px]">
                        <span class="text-ink-2">{row.name}</span>
                        <span class="font-mono tabular-nums">{pct(row.value)}</span>
                    </div>
                    <div class="h-1 rounded-full bg-raised">
                        {#if row.value !== null && row.value !== undefined}
                            <div class="h-1 rounded-full {row.bar}" style="width: {row.value * 100}%"></div>
                        {/if}
                    </div>
                </dd>
            {/each}
        </div>

        <div class="space-y-3">
            <dt class="text-[13px] text-ink-2">Thực thể</dt>
            <dd class="flex justify-between text-[13px]">
                <span class="text-ink-2">Trùng với nguồn</span>
                <span class="font-mono tabular-nums">{pct(breakdown.entity_overlap_ratio)}</span>
            </dd>
            <dd class="flex justify-between text-[13px]">
                <span class="text-ink-2">Thực thể mới</span>
                <span class="font-mono tabular-nums">{breakdown.new_entity_count ?? '—'}</span>
            </dd>
            {#if breakdown.new_entities?.length}
                <dd class="flex flex-wrap gap-1">
                    {#each breakdown.new_entities as ent}
                        <span class="rounded bg-raised px-1.5 py-0.5 font-mono text-xs">{ent}</span>
                    {/each}
                </dd>
            {/if}
        </div>

        <div class="space-y-3">
            <dt class="text-[13px] text-ink-2">LLM và guardrail</dt>
            <dd class="flex justify-between text-[13px]">
                <span class="text-ink-2">LLM cho là ngoài nguồn</span>
                <span class="font-mono tabular-nums">{pct(breakdown.vistral_extrinsic_prob)}</span>
            </dd>
            <dd class="flex justify-between gap-4 text-[13px]">
                <span class="text-ink-2">Luật đã kích hoạt</span>
                <span class="truncate font-mono text-xs {breakdown.active_guardrail ? 'text-warn' : 'text-ink-3'}" title={breakdown.active_guardrail ?? undefined}>
                    {breakdown.active_guardrail ?? 'Không'}
                </span>
            </dd>
        </div>
    </dl>
{:else}
    <p class="text-[13px] text-ink-3">Mô hình không trả về chi tiết cho kết quả này</p>
{/if}
