<!-- applications/web/src/lib/components/TraceView.svelte -->
<!-- RAG audit: the answer as a reviewed passage, each sentence marked and footnoted to the chunk behind its verdict -->
<script lang="ts">
    import { fly } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import { RotateCcw } from 'lucide-svelte';
    import type { AuditResponse } from '$lib/api/api';
    import { labelMeta, pct, TONE_TEXT } from '$lib/labels';
    import VerdictTag from './VerdictTag.svelte';
    import Breakdown from './Breakdown.svelte';
    import FeedbackPanel from './FeedbackPanel.svelte';
    import JudgePanel from './JudgePanel.svelte';
    import { createEventDispatcher } from 'svelte';

    export let result: AuditResponse;
    const dispatch = createEventDispatcher();

    $: claims = result.claims ?? [];
    $: contexts = result.contexts ?? [];
    $: metrics = result.rag_metrics;
    $: supported = claims.filter((c) => c.label === 'no').length;
    // A chunk "backs" a claim only when the claim is grounded in it
    $: backing = contexts.map((_, i) => claims.filter((c) => c.label === 'no' && c.context_index === i).length);

    let selected = 0;
    let hovered: number | null = null;
    $: if (selected >= claims.length) selected = 0;
    $: focusChunk = (hovered ?? selected) !== null && claims[hovered ?? selected]?.label !== 'extrinsic'
        ? claims[hovered ?? selected]?.context_index
        : null;

    const markClass = { ok: 'mark-ok', bad: 'mark-bad', warn: 'mark-warn', idle: '' };
</script>

<article in:fly={{ y: 8, duration: 320, easing: quintOut }} class="space-y-6">
    <!-- Summary -->
    <header class="flex flex-wrap items-end justify-between gap-6 rounded-xl border border-line bg-card px-6 py-5 shadow-[var(--shadow-sm)]">
        <div class="space-y-2">
            <VerdictTag label={result.label} long />
            <h2 class="text-xl font-medium">
                {supported} trên {claims.length} câu có tài liệu đỡ
            </h2>
            <p class="max-w-xl text-[13px] text-ink-2">{result.prompt}</p>
        </div>
        <dl class="flex flex-wrap gap-x-10 gap-y-4">
            <div>
                <dt class="text-[13px] text-ink-2">Độ bám nguồn</dt>
                <dd class="mt-1 text-[32px] leading-none font-medium tabular-nums {TONE_TEXT[labelMeta(result.label).tone]}">
                    {pct(result.faithfulness)}
                </dd>
            </div>
            <div>
                <dt class="text-[13px] text-ink-2">Đoạn nguồn được dùng</dt>
                <dd class="mt-1 text-xl leading-none font-medium tabular-nums">
                    {backing.filter((n) => n > 0).length}/{contexts.length}
                </dd>
            </div>
            <div title={metrics?.context_recall == null ? 'Cần đáp án chuẩn để tính' : ''}>
                <dt class="text-[13px] text-ink-2">Độ phủ đáp án chuẩn</dt>
                <dd class="mt-1 text-xl leading-none font-medium tabular-nums {metrics?.context_recall == null ? 'text-ink-3' : ''}">
                    {pct(metrics?.context_recall)}
                </dd>
            </div>
            <div title="Cosine PhoBERT, chỉ dùng để so sánh giữa các lần chạy">
                <dt class="text-[13px] text-ink-2">Liên quan câu hỏi</dt>
                <dd class="mt-1 font-mono text-xl leading-none tabular-nums {metrics?.answer_relevance == null ? 'text-ink-3' : ''}">
                    {metrics?.answer_relevance == null ? '—' : metrics.answer_relevance.toFixed(2)}
                </dd>
            </div>
        </dl>
    </header>

    <div class="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <!-- Answer as a reviewed passage -->
        <section class="space-y-4 rounded-xl border border-line bg-card p-6">
            <div class="flex flex-wrap items-center justify-between gap-3">
                <h3 class="text-sm font-medium">Câu trả lời</h3>
                <ul class="flex flex-wrap gap-4 text-xs text-ink-2" aria-label="Chú giải">
                    <li><span class="mark mark-ok">Khớp nguồn</span></li>
                    <li><span class="mark mark-bad">Mâu thuẫn</span></li>
                    <li><span class="mark mark-warn">Ngoài nguồn</span></li>
                </ul>
            </div>

            <p class="text-[15px] leading-8">
                {#each claims as claim, i}
                    {@const meta = labelMeta(claim.label)}
                    <button
                        type="button"
                        class="mark {markClass[meta.tone]} inline cursor-pointer text-left"
                        aria-pressed={selected === i}
                        aria-label="Câu {i + 1}: {meta.short}"
                        on:click={() => (selected = i)}
                        on:mouseenter={() => (hovered = i)}
                        on:mouseleave={() => (hovered = null)}
                        on:focus={() => (hovered = i)}
                        on:blur={() => (hovered = null)}
                    >{claim.text}{#if claim.label !== 'extrinsic'}<sup class="ml-0.5 font-mono text-[11px] {TONE_TEXT[meta.tone]}">[{claim.context_index + 1}]</sup>{/if}</button>{' '}
                {/each}
            </p>

            {#if claims[selected]}
                {@const claim = claims[selected]}
                <div class="space-y-4 border-t border-line pt-4">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                        <span class="text-[13px] text-ink-2">Câu {selected + 1}</span>
                        <span class="flex items-center gap-3">
                            <VerdictTag label={claim.label} />
                            <span class="font-mono text-xs text-ink-3 tabular-nums">tin cậy {pct(claim.confidence)}</span>
                        </span>
                    </div>
                    <Breakdown breakdown={claim.breakdown} />
                </div>
            {/if}
        </section>

        <!-- Sources -->
        <section class="space-y-3">
            <h3 class="px-1 text-sm font-medium">Tài liệu truy xuất</h3>
            {#each contexts as chunk, i}
                <div
                    class="rounded-xl border bg-card p-4 transition-colors duration-150 {focusChunk === i ? 'border-accent' : 'border-line'}"
                >
                    <div class="mb-2 flex items-center justify-between gap-3 text-xs">
                        <span class="font-mono text-ink-2">[{i + 1}]</span>
                        <span class="flex items-center gap-3 text-ink-3">
                            {#if metrics?.context_relevance?.[i] != null}
                                <span class="font-mono tabular-nums" title="Liên quan câu hỏi">{metrics.context_relevance[i].toFixed(2)}</span>
                            {/if}
                            <span class={backing[i] ? 'text-ok' : ''}>
                                {backing[i] ? `đỡ ${backing[i]} câu` : 'không được dùng'}
                            </span>
                        </span>
                    </div>
                    <p class="text-[13px] leading-6 {backing[i] ? 'text-ink' : 'text-ink-2'}">{chunk}</p>
                </div>
            {/each}
        </section>
    </div>

    <JudgePanel bind:result {claims} />

    <FeedbackPanel {result} />

    <footer class="flex flex-wrap items-center justify-between gap-3 text-xs text-ink-3">
        <span class="font-mono">
            {[result.id.slice(0, 8), result.model_version, result.latency_ms ? `${result.latency_ms.toFixed(0)} ms` : null].filter(Boolean).join(' · ')}
        </span>
        <button
            type="button"
            on:click={() => dispatch('reset')}
            class="inline-flex h-8 items-center gap-2 rounded-lg border border-line-strong bg-card px-3 text-[13px] text-ink transition-colors duration-150 hover:bg-raised"
        >
            <RotateCcw size={16} strokeWidth={1.5} /> Kiểm tra câu khác
        </button>
    </footer>
</article>
