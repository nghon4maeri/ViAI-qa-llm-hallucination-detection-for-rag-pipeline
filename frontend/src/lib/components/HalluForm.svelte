<!-- frontend/src/lib/components/HalluForm.svelte -->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { Zap, FileText, MessageSquare, Terminal, Loader2, Sparkles, RotateCcw } from 'lucide-svelte';

    export let isLoading = false;
    
    export let context = '';
    export let prompt = '';
    export let response = '';

    const dispatch = createEventDispatcher();
    const handleSubmit = () => {
        if (context && prompt && response) dispatch('submit', { context, prompt, response });
    };

    const PRESETS = [
        {
            title: 'Tin tức (Chính xác)',
            color: 'border-emerald-500/30 text-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20',
            context: 'Việt Nam có thủ đô là Hà Nội và là quốc gia đông dân thứ 15 trên thế giới với hơn 100 triệu dân.',
            prompt: 'Thủ đô của Việt Nam là thành phố nào?',
            response: 'Thủ đô của Việt Nam là Hà Nội.'
        },
        {
            title: 'Y tế (Mâu thuẫn)',
            color: 'border-rose-500/30 text-rose-400 bg-rose-500/10 hover:bg-rose-500/20',
            context: 'Thuốc Paracetamol hạ sốt cho người lớn dùng liều 500mg đến 1000mg mỗi lần, cách nhau tối thiểu 4 đến 6 giờ, tuyệt đối không uống quá 4000mg mỗi ngày vì nguy cơ suy gan cấp.',
            prompt: 'Tôi có thể uống Paracetamol 6000mg mỗi ngày được không?',
            response: 'Bạn hoàn toàn có thể uống 6000mg Paracetamol mỗi ngày để hạ sốt nhanh chóng hơn mà không gây hại cho gan.'
        },
        {
            title: 'Tài chính (Bịa đặt)',
            color: 'border-amber-500/30 text-amber-400 bg-amber-500/10 hover:bg-amber-500/20',
            context: 'Công ty Cổ phần Sữa Việt Nam (Vinamilk) ghi nhận doanh thu năm 2023 đạt hơn 60.000 tỷ đồng, tăng trưởng nhẹ so với năm trước.',
            prompt: 'Vinamilk đạt kết quả kinh doanh thế nào trong năm 2023?',
            response: 'Năm 2023, Vinamilk đạt doanh thu 60.000 tỷ đồng và mở thêm 500 chi nhánh bán lẻ mới tại thành phố Tokyo Nhật Bản.'
        }
    ];

    function applyPreset(preset: typeof PRESETS[0]) {
        context = preset.context;
        prompt = preset.prompt;
        response = preset.response;
    }

    function clearForm() {
        context = '';
        prompt = '';
        response = '';
    }
</script>

<div class="relative z-10 space-y-5 max-w-4xl mx-auto">
    <!-- Presets bar -->
    <div class="flex flex-wrap items-center justify-between gap-2 pb-2">
        <div class="flex items-center gap-1.5 text-xs text-slate-400 font-medium">
            <Sparkles size={14} class="text-indigo-400" />
            <span>Mẫu thử nghiệm nhanh:</span>
        </div>
        <div class="flex flex-wrap items-center gap-2">
            {#each PRESETS as p}
                <button 
                    type="button"
                    on:click={() => applyPreset(p)}
                    class="px-3 py-1 rounded-lg border text-xs font-medium transition-all {p.color}"
                >
                    {p.title}
                </button>
            {/each}
            {#if context || prompt || response}
                <button 
                    type="button"
                    on:click={clearForm}
                    class="px-2.5 py-1 rounded-lg border border-white/10 text-slate-400 hover:text-white hover:bg-white/5 text-xs font-medium transition-all flex items-center gap-1"
                    title="Xóa trắng form"
                >
                    <RotateCcw size={12} /> Xóa
                </button>
            {/if}
        </div>
    </div>

    <!-- Context Textarea -->
    <div class="group relative rounded-2xl bg-slate-900/50 border border-white/10 p-1 transition-all hover:border-indigo-500/50 hover:shadow-[0_0_20px_rgba(99,102,241,0.1)]">
        <div class="absolute -top-3 left-4 px-2 bg-[#030712] text-xs font-mono text-indigo-400 flex items-center gap-2">
            <FileText size={12} /> NGỮ CẢNH GỐC (CONTEXT SOURCE)
        </div>
        <textarea 
            bind:value={context} 
            placeholder="Dán văn bản nguồn chứa dữ liệu chuẩn (tài liệu, bài viết, báo cáo)..."
            class="w-full h-32 bg-transparent p-4 text-sm text-slate-200 placeholder:text-slate-600 outline-none resize-none font-mono leading-relaxed"
        ></textarea>
    </div>

    <!-- User Query & AI Response -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div class="group relative rounded-2xl bg-slate-900/50 border border-white/10 p-1 transition-all hover:border-pink-500/50 hover:shadow-[0_0_20px_rgba(236,72,153,0.1)]">
            <div class="absolute -top-3 left-4 px-2 bg-[#030712] text-xs font-mono text-pink-400 flex items-center gap-2">
                <MessageSquare size={12} /> CÂU HỎI NGƯỜI DÙNG (PROMPT)
            </div>
            <textarea 
                bind:value={prompt} 
                placeholder="Câu hỏi người dùng gửi cho AI..."
                class="w-full h-32 bg-transparent p-4 text-sm text-slate-200 placeholder:text-slate-600 outline-none resize-none font-mono leading-relaxed"
            ></textarea>
        </div>

        <div class="group relative rounded-2xl bg-slate-900/50 border border-white/10 p-1 transition-all hover:border-cyan-500/50 hover:shadow-[0_0_20px_rgba(6,182,212,0.1)]">
            <div class="absolute -top-3 left-4 px-2 bg-[#030712] text-xs font-mono text-cyan-400 flex items-center gap-2">
                <Terminal size={12} /> CÂU TRẢ LỜI CỦA AI (AI OUTPUT)
            </div>
            <textarea 
                bind:value={response} 
                placeholder="Câu trả lời của AI cần thẩm định..."
                class="w-full h-32 bg-transparent p-4 text-sm text-slate-200 placeholder:text-slate-600 outline-none resize-none font-mono leading-relaxed"
            ></textarea>
        </div>
    </div>

    <!-- Submit Button -->
    <div class="flex justify-center pt-2">
        <button 
            on:click={handleSubmit}
            disabled={isLoading || !context || !prompt || !response}
            class="relative group px-8 py-3.5 bg-gradient-to-r from-indigo-600 via-indigo-500 to-pink-600 rounded-full text-white font-bold shadow-lg shadow-indigo-500/30 hover:shadow-indigo-500/50 transition-all active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed overflow-hidden text-sm"
        >
            <div class="absolute inset-0 bg-white/20 group-hover:translate-x-full transition-transform duration-500 -skew-x-12 -translate-x-full"></div>
            <div class="flex items-center gap-2 relative z-10">
                {#if isLoading}
                    <Loader2 size={18} class="animate-spin" />
                    <span>ĐANG SUY LUẬN MÔ HÌNH...</span>
                {:else}
                    <Zap size={18} class="fill-white" />
                    <span>THẨM ĐỊNH CHẤT LƯỢNG (RUN QA)</span>
                {/if}
            </div>
        </button>
    </div>
</div>
