<!-- frontend/src/lib/components/BatchEvaluation.svelte -->
<script lang="ts">
    import { 
        UploadCloud, 
        FileSpreadsheet, 
        CheckCircle2, 
        AlertTriangle, 
        Download, 
        Loader2, 
        RotateCcw,
        BarChart,
        Clock
    } from 'lucide-svelte';
    import { uploadBatchCsv, fetchBatchStatus, getBatchExportUrl, type BatchDetailResponse } from '$lib/api/api';

    export let selectedProjectId: string = '';

    let selectedFile: File | null = null;
    let isUploading = false;
    let isProcessing = false;
    let batchDetail: BatchDetailResponse | null = null;
    let errorMessage: string | null = null;
    let pollInterval: any = null;

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
            errorMessage = err.message || 'Lỗi khi tải lên file CSV';
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

    async function loadSampleBatch() {
        const sampleCsv = 
`context,prompt,response
"Việt Nam có thủ đô là Hà Nội và là quốc gia đông dân thứ 15 trên thế giới với hơn 100 triệu dân.","Thủ đô của Việt Nam là thành phố nào?","Thủ đô của Việt Nam là Hà Nội."
"Nước sôi ở 100 độ C ở áp suất khí quyển tiêu chuẩn 1 atm.","Nước sôi ở bao nhiêu độ C ở áp suất tiêu chuẩn?","Nước sôi ở 100 độ C ở áp suất tiêu chuẩn."
"Mặt trời mọc ở hướng đông và lặn ở hướng tây mỗi ngày.","Mặt trời lặn ở hướng nào?","Mặt trời mọc ở hướng tây và lặn ở hướng đông."
"Sông Mê Kông chảy qua 6 quốc gia gồm Trung Quốc, Myanmar, Lào, Thái Lan, Campuchia và Việt Nam.","Sông Mê Kông chảy qua những quốc gia nào?","Sông Mê Kông chảy qua 6 quốc gia Đông Nam Á và Châu Á, bắt nguồn từ Tây Tạng."
"Nguyễn Du là một đại thi hào của dân tộc Việt Nam, tác giả của tác phẩm nổi tiếng Truyện Kiều.","Ai là tác giả của tác phẩm Truyện Kiều?","Truyện Kiều do đại thi hào Nguyễn Du sáng tác."
"Đại học Quốc gia Hà Nội được thành lập trên cơ sở tổ chức lại các trường đại học lớn ở Hà Nội.","Đại học Quốc gia Hà Nội nằm ở đâu?","Đại học Quốc gia Hà Nội nằm tại thủ đô Paris nước Pháp."
"Vịnh Hạ Long là một di sản thiên nhiên thế giới được UNESCO công nhận, nằm ở tỉnh Quảng Ninh.","Vịnh Hạ Long thuộc tỉnh nào của Việt Nam?","Vịnh Hạ Long thuộc tỉnh Quảng Ninh của Việt Nam."
"Hổ là loài thú ăn thịt lớn nhất trong họ Mèo, sinh sống chủ yếu ở các khu rừng nhiệt đới Châu Á.","Thức ăn chính của loài hổ là gì?","Hổ là loài thú ăn thịt, thức ăn chính của chúng là thịt động vật."
"Trái đất quay quanh Mặt trời theo quỹ đạo hình elip với chu kỳ khoảng 365,25 ngày một vòng.","Trái đất quay quanh thiên thể nào?","Trái đất quay quanh Mặt trăng mỗi 365 ngày."
"Asphalt là một dạng bitum bán rắn hoặc nhớt màu đen, thường dùng để rải mặt đường giao thông.","Chất liệu nào thường dùng để rải mặt đường giao thông?","Nhựa đường asphalt thường được sử dụng rộng rãi để rải mặt đường giao thông."`;

        const blob = new Blob([sampleCsv], { type: 'text/csv' });
        selectedFile = new File([blob], 'sample_vietnamese_qa.csv', { type: 'text/csv' });
        await startBatchUpload();
    }

    function resetBatch() {
        if (pollInterval) clearInterval(pollInterval);
        selectedFile = null;
        batchDetail = null;
        isProcessing = false;
        errorMessage = null;
    }

    const getBadge = (label?: string | null) => {
        const l = label?.toLowerCase() || '';
        if (l.includes('no') || l.includes('entail')) 
            return { text: 'CHÍNH XÁC', css: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' };
        if (l.includes('intrinsic') || l.includes('contra')) 
            return { text: 'MÂU THUẪN', css: 'text-rose-400 border-rose-500/30 bg-rose-500/10' };
        if (l.includes('extrinsic'))
            return { text: 'BỊA ĐẶT', css: 'text-amber-400 border-amber-500/30 bg-amber-500/10' };
        return { text: 'ĐANG CHỜ', css: 'text-slate-400 border-slate-500/30 bg-slate-500/10' };
    };
</script>

<div class="space-y-6">
    <!-- Upload Box or Progress State -->
    {#if !batchDetail}
        <div class="p-8 rounded-2xl border-2 border-dashed border-white/10 hover:border-indigo-500/40 bg-slate-900/40 backdrop-blur-md transition-all text-center">
            <div class="flex flex-col items-center justify-center max-w-lg mx-auto space-y-4">
                <div class="p-4 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 shadow-inner">
                    <FileSpreadsheet size={36} />
                </div>
                <div>
                    <h3 class="text-lg font-bold text-white mb-1">Tải Lên Bộ Test Case (CSV)</h3>
                    <p class="text-xs text-slate-400 leading-relaxed">
                        Tệp CSV cần chứa 3 cột: <code class="text-indigo-300 font-mono">context</code>, <code class="text-indigo-300 font-mono">prompt</code>, <code class="text-indigo-300 font-mono">response</code>.
                    </p>
                </div>

                <div class="flex flex-wrap items-center justify-center gap-3 pt-2">
                    <label class="cursor-pointer px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold transition-all shadow-lg shadow-indigo-600/30 flex items-center gap-2">
                        <UploadCloud size={16} />
                        Chọn tệp CSV từ máy tính
                        <input type="file" accept=".csv" on:change={handleFileChange} class="hidden" />
                    </label>

                    <button 
                        on:click={loadSampleBatch}
                        class="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-xs font-medium transition-all"
                    >
                        Tải bộ dữ liệu mẫu (10 câu)
                    </button>
                </div>

                {#if selectedFile}
                    <div class="mt-4 p-3 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-xs text-indigo-300 flex items-center justify-between w-full">
                        <span class="font-mono truncate">{selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)</span>
                        <button 
                            disabled={isUploading}
                            on:click={startBatchUpload}
                            class="px-3 py-1 rounded-lg bg-indigo-500 text-white font-bold hover:bg-indigo-400 disabled:opacity-50"
                        >
                            {#if isUploading}Đang gửi...{:else}Bắt đầu đánh giá{/if}
                        </button>
                    </div>
                {/if}

                {#if errorMessage}
                    <p class="text-xs text-rose-400 font-mono">⚠ {errorMessage}</p>
                {/if}
            </div>
        </div>
    {:else}
        <!-- Batch Results & Progress Dashboard -->
        <div class="space-y-6">
            <!-- Summary Stats Card -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div class="p-4 rounded-xl bg-slate-900/60 border border-white/10">
                    <span class="text-[11px] font-bold text-slate-400 uppercase">Tổng số mẫu</span>
                    <div class="text-2xl font-black text-white mt-1">{batchDetail.total_count}</div>
                    <span class="text-[10px] text-slate-500 font-mono">{batchDetail.filename}</span>
                </div>

                <div class="p-4 rounded-xl bg-slate-900/60 border border-white/10">
                    <span class="text-[11px] font-bold text-slate-400 uppercase">Tiến độ</span>
                    <div class="text-2xl font-black text-cyan-400 mt-1">
                        {batchDetail.completed_count} / {batchDetail.total_count}
                    </div>
                    <span class="text-[10px] text-slate-500 font-mono">
                        {batchDetail.status === 'COMPLETED' ? 'Hoàn thành 100%' : 'Đang xử lý trong background...'}
                    </span>
                </div>

                <div class="p-4 rounded-xl bg-slate-900/60 border border-white/10">
                    <span class="text-[11px] font-bold text-slate-400 uppercase">Số lỗi ảo giác</span>
                    <div class="text-2xl font-black text-rose-400 mt-1">
                        {batchDetail.hallucination_count}
                    </div>
                    <span class="text-[10px] text-slate-500">Mâu thuẫn hoặc bịa đặt</span>
                </div>

                <div class="p-4 rounded-xl bg-slate-900/60 border border-white/10">
                    <span class="text-[11px] font-bold text-slate-400 uppercase">Tỷ lệ ảo giác</span>
                    <div class="text-2xl font-black {batchDetail.hallucination_rate > 20 ? 'text-amber-400' : 'text-emerald-400'} mt-1">
                        {batchDetail.hallucination_rate}%
                    </div>
                    <span class="text-[10px] text-slate-500">Hallucination Rate</span>
                </div>
            </div>

            <!-- Progress Bar -->
            {#if isProcessing}
                <div class="p-4 rounded-xl bg-slate-900/40 border border-indigo-500/20 space-y-2">
                    <div class="flex justify-between text-xs text-indigo-300">
                        <span class="flex items-center gap-2">
                            <Loader2 size={14} class="animate-spin" /> Đang chạy suy luận ML...
                        </span>
                        <span class="font-mono font-bold">
                            {((batchDetail.completed_count / (batchDetail.total_count || 1)) * 100).toFixed(0)}%
                        </span>
                    </div>
                    <div class="h-2 w-full bg-slate-950 rounded-full overflow-hidden">
                        <div 
                            class="h-full bg-gradient-to-r from-indigo-500 to-pink-500 transition-all duration-500"
                            style="width: {(batchDetail.completed_count / (batchDetail.total_count || 1)) * 100}%"
                        ></div>
                    </div>
                </div>
            {/if}

            <!-- Action Buttons -->
            <div class="flex items-center justify-between">
                <h4 class="text-sm font-bold text-slate-200">Chi tiết kết quả thẩm định ({batchDetail.items.length} câu)</h4>
                
                <div class="flex gap-2">
                    <a 
                        href={getBatchExportUrl(batchDetail.id)}
                        download={`batch_${batchDetail.id}.csv`}
                        class="px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition-all flex items-center gap-1.5 shadow-lg shadow-emerald-600/20"
                    >
                        <Download size={14} /> Xuất file CSV
                    </a>

                    <button 
                        on:click={resetBatch}
                        class="px-3.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium transition-all flex items-center gap-1.5"
                    >
                        <RotateCcw size={14} /> Tải lô mới
                    </button>
                </div>
            </div>

            <!-- Table of Results -->
            <div class="rounded-xl border border-white/10 bg-slate-900/40 backdrop-blur-md overflow-hidden">
                <div class="overflow-x-auto max-h-[450px] custom-scrollbar">
                    <table class="w-full text-left text-xs">
                        <thead class="bg-white/5 text-slate-400 font-bold uppercase text-[10px] sticky top-0 backdrop-blur-md">
                            <tr>
                                <th class="p-3">#</th>
                                <th class="p-3">Câu hỏi (Prompt)</th>
                                <th class="p-3">Câu trả lời (Response)</th>
                                <th class="p-3">Kết luận</th>
                                <th class="p-3 text-right">Độ tin cậy</th>
                                <th class="p-3 text-right">Thời gian</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-white/5 text-slate-300">
                            {#each batchDetail.items as item, index}
                                {@const badge = getBadge(item.label)}
                                <tr class="hover:bg-white/[0.02] transition-colors">
                                    <td class="p-3 text-slate-500 font-mono text-[10px]">{index + 1}</td>
                                    <td class="p-3 font-medium text-slate-200 max-w-xs truncate" title={item.prompt}>{item.prompt}</td>
                                    <td class="p-3 text-slate-300 max-w-sm truncate" title={item.response}>{item.response}</td>
                                    <td class="p-3">
                                        <span class="text-[9px] font-black px-1.5 py-0.5 rounded border {badge.css}">
                                            {badge.text}
                                        </span>
                                    </td>
                                    <td class="p-3 text-right font-mono text-cyan-400 font-bold">
                                        {item.confidence !== null && item.confidence !== undefined ? `${(item.confidence * 100).toFixed(0)}%` : '--'}
                                    </td>
                                    <td class="p-3 text-right font-mono text-slate-500 text-[10px]">
                                        {item.latency_ms ? `${item.latency_ms.toFixed(0)}ms` : '--'}
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    {/if}
</div>
