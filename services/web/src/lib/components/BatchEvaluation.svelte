<!-- services/web/src/lib/components/BatchEvaluation.svelte -->
<script lang="ts">
    import { Upload, Download, Loader2, RotateCcw } from 'lucide-svelte';
    import { uploadBatchCsv, fetchBatchStatus, getBatchExportUrl, type BatchDetailResponse } from '$lib/api/api';
    import { pct } from '$lib/labels';
    import VerdictTag from './VerdictTag.svelte';

    export let selectedProjectId: string = '';

    let selectedFile: File | null = null;
    let isUploading = false;
    let isProcessing = false;
    let batchDetail: BatchDetailResponse | null = null;
    let errorMessage: string | null = null;
    let pollInterval: any = null;

    $: isRag = batchDetail?.mean_faithfulness !== null && batchDetail?.mean_faithfulness !== undefined;
    $: progress = batchDetail ? batchDetail.completed_count / (batchDetail.total_count || 1) : 0;

    function handleFileChange(event: Event) {
        const input = event.target as HTMLInputElement;
        if (input.files && input.files[0]) {
            selectedFile = input.files[0];
            errorMessage = null;
        }
    }

    async function startBatchUpload() {
        if (!selectedFile) return;
        isUploading = true;
        errorMessage = null;

        try {
            const uploadRes = await uploadBatchCsv(selectedFile, selectedProjectId || undefined);
            isUploading = false;
            isProcessing = true;
            pollBatchStatus(uploadRes.batch_id);
        } catch (err: any) {
            isUploading = false;
            errorMessage = err.message || 'Không tải lên được tệp';
        }
    }

    function pollBatchStatus(batchId: string) {
        if (pollInterval) clearInterval(pollInterval);

        pollInterval = setInterval(async () => {
            try {
                const detail = await fetchBatchStatus(batchId);
                batchDetail = detail;

                if (detail.status === 'COMPLETED' || detail.status === 'FAILED') {
                    clearInterval(pollInterval);
                    pollInterval = null;
                    isProcessing = false;
                }
            } catch (err) {
                console.warn('Poll error:', err);
            }
        }, 1500);
    }

    // Medical samples, one per verdict, so a first run shows every outcome
    const SAMPLE_CSV =
`context,prompt,response
"Thời điểm dùng thuốc: uống ngay trước hoặc trong bữa ăn. Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy.","Uống thuốc Comiaryl đúng cách như thế nào?","Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy."
"Không uống quá 4000mg Paracetamol mỗi ngày vì nguy cơ suy gan cấp.","Người lớn được uống tối đa bao nhiêu Paracetamol mỗi ngày?","Người lớn có thể uống tới 6000mg Paracetamol mỗi ngày."
"Vitamin D3 Aquadetrim nên được bảo quản ở những nơi khô ráo, thoáng mát.","Bảo quản Vitamin D3 Aquadetrim thế nào?","Bảo quản thuốc ở nơi khô ráo. Tổng thống khuyên dùng loại vitamin này."`;

    const SAMPLE_JSONL = [
        { question: 'Uống thuốc Comiaryl đúng cách như thế nào?', contexts: ['Thời điểm dùng thuốc: uống ngay trước hoặc trong bữa ăn.', 'Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy.'], answer: 'Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy. Uống ngay trước hoặc trong bữa ăn.', ground_truth: 'Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy.' },
        { question: 'Bảo quản Vitamin D3 Aquadetrim thế nào?', contexts: ['Vitamin D3 Aquadetrim nên được bảo quản ở những nơi khô ráo, thoáng mát.'], answer: 'Bảo quản ở nơi khô ráo, thoáng mát. Tổng thống khuyên dùng loại vitamin này.' },
    ].map((r) => JSON.stringify(r)).join('\n');

    async function loadSample(kind: 'csv' | 'jsonl') {
        const body = kind === 'csv' ? SAMPLE_CSV : SAMPLE_JSONL;
        selectedFile = new File([body], kind === 'csv' ? 'mau_y_te.csv' : 'mau_rag_y_te.jsonl', { type: 'text/plain' });
        await startBatchUpload();
    }

    function resetBatch() {
        if (pollInterval) clearInterval(pollInterval);
        selectedFile = null;
        batchDetail = null;
        isProcessing = false;
        errorMessage = null;
    }

    const secondary = 'inline-flex h-9 items-center gap-2 rounded-lg border border-line-strong bg-card px-3 text-[13px] transition-colors duration-150 hover:bg-raised';
</script>

{#if !batchDetail}
    <section class="space-y-6 rounded-xl border border-line bg-card p-6">
        <div class="space-y-2">
            <h2 class="text-base font-medium">Đánh giá một bộ dữ liệu</h2>
            <p class="max-w-2xl text-[13px] leading-6 text-ink-2">
                Tệp <span class="font-mono text-ink">.csv</span> với các cột <span class="font-mono text-ink">context, prompt, response</span>,
                hoặc tệp <span class="font-mono text-ink">.jsonl</span> mỗi dòng một lượt RAG:
                <span class="font-mono text-ink">question, contexts, answer, ground_truth</span>
            </p>
        </div>

        <div class="flex flex-wrap items-center gap-2">
            <label class="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg bg-accent px-4 text-[13px] font-medium text-on-accent transition-colors duration-150 hover:bg-accent-hover">
                <Upload size={16} strokeWidth={1.5} /> Chọn tệp
                <input type="file" accept=".csv,.jsonl" on:change={handleFileChange} class="sr-only" />
            </label>
            <button type="button" on:click={() => loadSample('csv')} class={secondary}>Chạy mẫu CSV</button>
            <button type="button" on:click={() => loadSample('jsonl')} class={secondary}>Chạy mẫu RAG</button>
        </div>

        {#if selectedFile}
            <div class="flex items-center justify-between gap-4 rounded-lg bg-raised px-4 py-3 text-[13px]">
                <span class="truncate font-mono">{selectedFile.name} · {(selectedFile.size / 1024).toFixed(1)} KB</span>
                <button
                    type="button"
                    disabled={isUploading}
                    on:click={startBatchUpload}
                    class="h-8 rounded-lg bg-accent px-3 font-medium text-on-accent disabled:opacity-50"
                >{isUploading ? 'Đang gửi' : 'Bắt đầu'}</button>
            </div>
        {/if}

        {#if errorMessage}
            <p class="text-[13px] text-bad">{errorMessage}</p>
        {/if}
    </section>
{:else}
    <section class="space-y-6">
        <dl class="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div class="rounded-xl border border-line bg-card px-5 py-4">
                <dt class="text-[13px] text-ink-2">Đã chấm</dt>
                <dd class="mt-2 text-[28px] leading-none font-medium tabular-nums">{batchDetail.completed_count}/{batchDetail.total_count}</dd>
                <dd class="mt-2 truncate font-mono text-xs text-ink-3">{batchDetail.filename}</dd>
            </div>
            <div class="rounded-xl border border-line bg-card px-5 py-4">
                <dt class="text-[13px] text-ink-2">Có ảo giác</dt>
                <dd class="mt-2 text-[28px] leading-none font-medium tabular-nums">{batchDetail.hallucination_count}</dd>
                <dd class="mt-2 text-xs text-ink-3">mâu thuẫn hoặc ngoài nguồn</dd>
            </div>
            <div class="rounded-xl border border-line bg-card px-5 py-4">
                <dt class="text-[13px] text-ink-2">Tỷ lệ ảo giác</dt>
                <dd class="mt-2 text-[28px] leading-none font-medium tabular-nums">{batchDetail.hallucination_rate}%</dd>
                <dd class="mt-2 text-xs text-ink-3">trên số mẫu đã chấm</dd>
            </div>
            <div class="rounded-xl border border-line bg-card px-5 py-4">
                <dt class="text-[13px] text-ink-2">Độ bám nguồn trung bình</dt>
                <dd class="mt-2 text-[28px] leading-none font-medium tabular-nums {isRag ? 'text-accent' : 'text-ink-3'}">{pct(batchDetail.mean_faithfulness)}</dd>
                <dd class="mt-2 text-xs text-ink-3">{isRag ? 'các lượt RAG' : 'chỉ có với tệp RAG'}</dd>
            </div>
        </dl>

        {#if isProcessing}
            <div class="space-y-2" aria-live="polite">
                <div class="flex justify-between text-[13px] text-ink-2">
                    <span class="inline-flex items-center gap-2"><Loader2 size={16} strokeWidth={1.5} class="animate-spin" /> Đang chấm</span>
                    <span class="font-mono tabular-nums">{(progress * 100).toFixed(0)}%</span>
                </div>
                <div class="h-1 rounded-full bg-raised">
                    <div class="h-1 rounded-full bg-accent transition-transform duration-300 origin-left" style="transform: scaleX({progress})"></div>
                </div>
            </div>
        {/if}

        <div class="flex flex-wrap items-center justify-between gap-3">
            <h3 class="text-sm font-medium">Kết quả từng mẫu</h3>
            <div class="flex gap-2">
                <a href={getBatchExportUrl(batchDetail.id)} download={`batch_${batchDetail.id}.csv`} class={secondary}>
                    <Download size={16} strokeWidth={1.5} /> Xuất CSV
                </a>
                <button type="button" on:click={resetBatch} class={secondary}>
                    <RotateCcw size={16} strokeWidth={1.5} /> Bộ dữ liệu khác
                </button>
            </div>
        </div>

        <div class="overflow-hidden rounded-xl border border-line bg-card">
            <div class="max-h-[480px] overflow-auto">
                <table class="w-full text-left text-[13px]">
                    <thead class="sticky top-0 whitespace-nowrap bg-raised text-ink-2">
                        <tr>
                            <th class="px-4 py-2 font-medium">#</th>
                            <th class="px-4 py-2 font-medium">Câu hỏi</th>
                            <th class="px-4 py-2 font-medium">Câu trả lời</th>
                            <th class="px-4 py-2 font-medium">Kết luận</th>
                            {#if isRag}<th class="px-4 py-2 text-right font-medium">Bám nguồn</th>{/if}
                            <th class="px-4 py-2 text-right font-medium">Tin cậy</th>
                            <th class="px-4 py-2 text-right font-medium">Thời gian</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-line">
                        {#each batchDetail.items as item, index}
                            <tr class="transition-colors duration-150 hover:bg-raised/60">
                                <td class="px-4 py-2 font-mono text-xs text-ink-3">{index + 1}</td>
                                <td class="max-w-xs truncate px-4 py-2" title={item.prompt}>{item.prompt}</td>
                                <td class="max-w-sm truncate px-4 py-2 text-ink-2" title={item.response}>{item.response}</td>
                                <td class="whitespace-nowrap px-4 py-2"><VerdictTag label={item.label} /></td>
                                {#if isRag}<td class="px-4 py-2 text-right font-mono tabular-nums">{pct(item.faithfulness)}</td>{/if}
                                <td class="px-4 py-2 text-right font-mono tabular-nums">{pct(item.confidence)}</td>
                                <td class="px-4 py-2 text-right font-mono text-xs text-ink-3 tabular-nums">{item.latency_ms ? `${item.latency_ms.toFixed(0)} ms` : '—'}</td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        </div>
    </section>
{/if}
