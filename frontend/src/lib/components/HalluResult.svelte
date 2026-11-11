<!-- frontend/src/lib/components/HalluResult.svelte -->
<script lang="ts">
    import type { AuditResponse } from '$lib/api/api';
    import { submitFeedback } from '$lib/api/api';
    import { 
        ShieldCheck, 
        Ban, 
        AlertOctagon, 
        RotateCcw, 
        CheckCircle2, 
        Sparkles, 
        BarChart3, 
        Cpu, 
        Layers, 
        SendHorizontal,
        MessageSquare,
        Clock,
        Copy
    } from 'lucide-svelte';
    import { fly, fade } from 'svelte/transition';
    import { createEventDispatcher } from 'svelte';

    export let result: AuditResponse;
    const dispatch = createEventDispatcher();

    let feedbackLabel = '';
    let feedbackComment = '';
    let isSubmittingFeedback = false;
    let feedbackSubmitted = !!result.feedback;
    let feedbackSuccessMsg = '';
    let feedbackError = '';
    let copiedReport = false;

    async function copyBugReport() {
        const md = 
`### 🚨 ViAI-QA Bug Report
- **Audit ID**: \`${result.id}\`
- **Kết luận**: **${result.label?.toUpperCase()}** (${((result.confidence || 0) * 100).toFixed(1)}% độ tin cậy)
- **Thời gian suy luận**: ${result.latency_ms ? result.latency_ms.toFixed(1) + 'ms' : 'N/A'}
- **Ngữ cảnh (Context)**:
> ${result.context}
- **Câu hỏi (Prompt)**:
> ${result.prompt}
- **Câu trả lời (Response)**:
> ${result.response}
- **NLI Scores**: Entailment: ${((result.breakdown?.nli_entailment || 0) * 100).toFixed(0)}%, Contradiction: ${((result.breakdown?.nli_contradiction || 0) * 100).toFixed(0)}%
- **NER Overlap**: ${result.breakdown?.ner_overlap_ratio !== null && result.breakdown?.ner_overlap_ratio !== undefined ? (result.breakdown.ner_overlap_ratio * 100).toFixed(0) + '%' : 'N/A'}, Thực thể mới: ${result.breakdown?.ner_new_entity_count ?? 0}
`;
        try {
            await navigator.clipboard.writeText(md);
            copiedReport = true;
            setTimeout(() => copiedReport = false, 2500);
        } catch (e) {
            console.error('Clipboard copy error', e);
        }
    }

    $: theme = (() => {
        const l = result.label?.toLowerCase() || '';

        if (l.includes('no') || l.includes('entailment')) {
            return { 
                color: 'text-emerald-400', 
                border: 'border-emerald-500/40', 
                bg: 'from-emerald-950/40', 
                badgeBg: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
                icon: ShieldCheck, 
                title: 'CHÍNH XÁC (NO HALLUCINATION)',
                desc: 'Thông tin hoàn toàn khớp và được suy luận logic từ dữ liệu nguồn.'
            };
        }
        
        if (l.includes('intrinsic') || l.includes('contradiction')) {
            return { 
                color: 'text-rose-400', 
                border: 'border-rose-500/40', 
                bg: 'from-rose-950/40', 
                badgeBg: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
                icon: Ban, 
                title: 'MÂU THUẪN (INTRINSIC HALLUCINATION)',
                desc: 'Câu trả lời trực tiếp sai lệch hoặc mâu thuẫn với ngữ cảnh gốc.'
            };
        }

        return { 
            color: 'text-amber-400', 
            border: 'border-amber-500/40', 
            bg: 'from-amber-950/40', 
            badgeBg: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
            icon: AlertOctagon, 
            title: 'BỊA ĐẶT (EXTRINSIC HALLUCINATION)',
            desc: 'Câu trả lời chứa thực thể hoặc tuyên bố không hề tồn tại trong ngữ cảnh.'
        };
    })();

    async function handleFeedbackSubmit(selectedLabel: string) {
        if (!result.id) return;
        isSubmittingFeedback = true;
        feedbackError = '';

        try {
            const fb = await submitFeedback(result.id, {
                feedback_label: selectedLabel,
                corrected_label: selectedLabel,
                comment: feedbackComment || undefined,
            });
            result.feedback = fb;
            feedbackSubmitted = true;
            feedbackSuccessMsg = 'Đã lưu phản hồi của bạn vào cơ sở dữ liệu!';
        } catch (err: any) {
            feedbackError = err.message || 'Lỗi gửi phản hồi';
        } finally {
            isSubmittingFeedback = false;
        }
    }
</script>

<div in:fly={{ y: 20, duration: 400 }} class="relative z-20 w-full space-y-4">
    <!-- Main Result Card -->
    <div class="relative rounded-2xl border {theme.border} bg-gradient-to-br {theme.bg} to-slate-950/90 backdrop-blur-xl p-6 shadow-2xl overflow-hidden">
        <div class="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
            <div class="flex items-center gap-4">
                <div class="p-3.5 rounded-xl bg-white/5 border border-white/10 shadow-inner">
                    <svelte:component this={theme.icon} size={36} class={theme.color} />
                </div>
                <div>
                    <div class="flex items-center gap-2 mb-1">
                        <span class="text-xs font-mono font-bold px-2 py-0.5 rounded border {theme.badgeBg}">
                            {result.label?.toUpperCase() || 'UNKNOWN'}
                        </span>
                        {#if result.latency_ms}
                            <span class="text-[11px] font-mono text-slate-400 flex items-center gap-1 bg-white/5 px-2 py-0.5 rounded">
                                <Clock size={12} /> {result.latency_ms.toFixed(1)}ms
                            </span>
                        {/if}
                    </div>
                    <h3 class="text-xl md:text-2xl font-black tracking-wide text-white">{theme.title}</h3>
                    <p class="text-xs text-slate-300 max-w-xl">{theme.desc}</p>
                </div>
            </div>

            <div class="text-left md:text-right flex md:flex-col items-center md:items-end gap-3 md:gap-0">
                <div class="text-3xl md:text-4xl font-extrabold {theme.color}">
                    {((result.confidence || 0) * 100).toFixed(1)}%
                </div>
                <div class="text-[10px] text-slate-400 font-bold uppercase tracking-wider">Độ Tin Cậy</div>
            </div>
        </div>

        <!-- Confidence Gauge Bar -->
        <div class="mt-5 h-2 w-full bg-slate-900 rounded-full overflow-hidden p-0.5 border border-white/5">
            <div 
                class="h-full rounded-full {theme.color.replace('text', 'bg')} shadow-[0_0_12px_currentColor] transition-all duration-1000" 
                style="width: {(result.confidence || 0) * 100}%"
            ></div>
        </div>
    </div>

    <!-- Explainability Metric Breakdown Grid -->
    {#if result.breakdown}
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <!-- NLI Breakdown -->
            <div class="p-4 rounded-xl bg-slate-900/60 border border-white/10 backdrop-blur-md">
                <div class="flex items-center gap-2 text-indigo-400 text-xs font-bold uppercase tracking-wider mb-3">
                    <Layers size={16} /> Suy Luận Logic (NLI)
                </div>
                <div class="space-y-2 text-xs">
                    <div>
                        <div class="flex justify-between text-slate-300 mb-1">
                            <span>Khẳng định (Entailment)</span>
                            <span class="font-mono text-emerald-400">{((result.breakdown.nli_entailment || 0) * 100).toFixed(0)}%</span>
                        </div>
                        <div class="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                            <div class="h-full bg-emerald-500 rounded-full" style="width: {(result.breakdown.nli_entailment || 0) * 100}%"></div>
                        </div>
                    </div>
                    <div>
                        <div class="flex justify-between text-slate-300 mb-1">
                            <span>Mâu thuẫn (Contradiction)</span>
                            <span class="font-mono text-rose-400">{((result.breakdown.nli_contradiction || 0) * 100).toFixed(0)}%</span>
                        </div>
                        <div class="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                            <div class="h-full bg-rose-500 rounded-full" style="width: {(result.breakdown.nli_contradiction || 0) * 100}%"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- NER Overlap -->
            <div class="p-4 rounded-xl bg-slate-900/60 border border-white/10 backdrop-blur-md">
                <div class="flex items-center gap-2 text-cyan-400 text-xs font-bold uppercase tracking-wider mb-3">
                    <BarChart3 size={16} /> Thực Thể & Từ Ngữ (NER)
                </div>
                <div class="space-y-3 text-xs">
                    <div class="flex justify-between items-center bg-white/[0.02] p-2 rounded-lg">
                        <span class="text-slate-300">Tỷ lệ trùng khớp thực thể:</span>
                        <span class="font-mono font-bold text-cyan-400">
                            {result.breakdown.ner_overlap_ratio !== null && result.breakdown.ner_overlap_ratio !== undefined
                                ? `${(result.breakdown.ner_overlap_ratio * 100).toFixed(0)}%`
                                : 'N/A'}
                        </span>
                    </div>
                    <div class="flex justify-between items-center bg-white/[0.02] p-2 rounded-lg">
                        <span class="text-slate-300">Thực thể mới phát hiện:</span>
                        <span class="font-mono font-bold {result.breakdown.ner_new_entity_count && result.breakdown.ner_new_entity_count > 0 ? 'text-amber-400' : 'text-slate-400'}">
                            {result.breakdown.ner_new_entity_count ?? 0} thực thể
                        </span>
                    </div>
                </div>
            </div>

            <!-- LLM Uncertainty & Guardrails -->
            <div class="p-4 rounded-xl bg-slate-900/60 border border-white/10 backdrop-blur-md">
                <div class="flex items-center gap-2 text-purple-400 text-xs font-bold uppercase tracking-wider mb-3">
                    <Cpu size={16} /> Vistral LLM & Guardrails
                </div>
                <div class="space-y-3 text-xs">
                    <div class="flex justify-between items-center bg-white/[0.02] p-2 rounded-lg">
                        <span class="text-slate-300">Xác suất ngoại lai LLM:</span>
                        <span class="font-mono font-bold text-purple-400">
                            {result.breakdown.llm_uncertainty !== null && result.breakdown.llm_uncertainty !== undefined
                                ? `${(result.breakdown.llm_uncertainty * 100).toFixed(0)}%`
                                : '0%'}
                        </span>
                    </div>
                    <div class="flex justify-between items-center bg-white/[0.02] p-2 rounded-lg">
                        <span class="text-slate-300">Guardrail kích hoạt:</span>
                        <span class="font-mono text-[10px] px-2 py-0.5 rounded bg-white/5 {result.breakdown.active_guardrail ? 'text-amber-300 border border-amber-500/30' : 'text-slate-500'}">
                            {result.breakdown.active_guardrail || 'None'}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    {/if}

    <!-- Human-in-the-Loop Feedback Section -->
    <div class="rounded-xl border border-white/10 bg-slate-900/40 backdrop-blur-md p-4">
        <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2 text-indigo-400 text-xs font-bold uppercase tracking-wider">
                <MessageSquare size={16} /> Đánh Giá Lại (Human-in-the-loop Annotation)
            </div>
            {#if feedbackSubmitted}
                <span class="text-xs text-emerald-400 flex items-center gap-1 font-medium">
                    <CheckCircle2 size={14} /> Đã gửi phản hồi ({result.feedback?.feedback_label})
                </span>
            {/if}
        </div>

        {#if !feedbackSubmitted}
            <div class="space-y-3">
                <p class="text-xs text-slate-400">
                    Mô hình có nhận định chính xác không? Nhãn bạn cung cấp sẽ được lưu vào PostgreSQL để huấn luyện lại mô hình trong chu trình MLOps:
                </p>
                
                <div class="flex flex-wrap gap-2">
                    <button 
                        disabled={isSubmittingFeedback}
                        on:click={() => handleFeedbackSubmit('CORRECT')}
                        class="px-3 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 text-xs font-medium transition-all"
                    >
                        ✓ Đồng ý với kết quả
                    </button>
                    <button 
                        disabled={isSubmittingFeedback}
                        on:click={() => handleFeedbackSubmit('intrinsic')}
                        class="px-3 py-1.5 rounded-lg border border-rose-500/30 bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 text-xs font-medium transition-all"
                    >
                        ✕ Là Mâu thuẫn (Intrinsic)
                    </button>
                    <button 
                        disabled={isSubmittingFeedback}
                        on:click={() => handleFeedbackSubmit('extrinsic')}
                        class="px-3 py-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 text-xs font-medium transition-all"
                    >
                        ✕ Là Bịa đặt (Extrinsic)
                    </button>
                    <button 
                        disabled={isSubmittingFeedback}
                        on:click={() => handleFeedbackSubmit('no_hallucination')}
                        class="px-3 py-1.5 rounded-lg border border-cyan-500/30 bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 text-xs font-medium transition-all"
                    >
                        ✕ Thực tế là Chính xác
                    </button>
                </div>

                <div class="flex gap-2">
                    <input 
                        type="text" 
                        bind:value={feedbackComment} 
                        placeholder="Ghi chú thêm (vd: từ ngữ cụ thể gây nhầm lẫn)..." 
                        class="flex-1 px-3 py-1.5 text-xs bg-slate-950/60 border border-white/10 rounded-lg text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500"
                    />
                </div>

                {#if feedbackError}
                    <p class="text-xs text-rose-400 font-mono">⚠ {feedbackError}</p>
                {/if}
            </div>
        {:else}
            <div class="text-xs text-slate-300 bg-white/[0.02] p-3 rounded-lg border border-white/5 space-y-1">
                <div class="flex items-center gap-2">
                    <span class="text-slate-500">Nhãn sửa đổi:</span>
                    <span class="font-mono text-emerald-400 font-bold">{result.feedback?.corrected_label}</span>
                </div>
                {#if result.feedback?.comment}
                    <div class="flex items-center gap-2">
                        <span class="text-slate-500">Ghi chú:</span>
                        <span class="text-slate-300">{result.feedback.comment}</span>
                    </div>
                {/if}
            </div>
        {/if}
    </div>

    <!-- Bottom Actions -->
    <div class="flex flex-wrap justify-between items-center gap-2 pt-2">
        <span class="text-[11px] font-mono text-slate-500">
            Audit ID: {result.id} | Engine: {result.model_version}
        </span>
        <div class="flex items-center gap-2">
            <button 
                on:click={copyBugReport}
                class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 hover:text-white text-xs font-medium transition-all border border-white/10"
                title="Sao chép báo cáo lỗi Markdown để dán vào Jira, Slack, GitHub"
            >
                {#if copiedReport}
                    <CheckCircle2 size={13} class="text-emerald-400" />
                    <span class="text-emerald-400 font-bold">Đã sao chép!</span>
                {:else}
                    <Copy size={13} />
                    <span>Copy Báo Cáo Jira/Slack</span>
                {/if}
            </button>
            <button 
                on:click={() => dispatch('reset')}
                class="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold transition-all border border-slate-700 hover:border-indigo-500"
            >
                <RotateCcw size={14} />
                Đánh Giá Mẫu Tiếp Theo
            </button>
        </div>
    </div>
</div>
