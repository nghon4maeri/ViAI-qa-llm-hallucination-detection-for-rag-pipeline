<!-- frontend/src/routes/+page.svelte -->
<script lang="ts">
    import { onMount } from 'svelte';
    import Header from '$lib/components/Header.svelte';
    import HalluForm from '$lib/components/HalluForm.svelte';
    import HalluResult from '$lib/components/HalluResult.svelte';
    import BatchEvaluation from '$lib/components/BatchEvaluation.svelte';
    import { 
        submitAudit, 
        fetchAuditHistory, 
        fetchAuditDetail, 
        type AuditSummary, 
        type AuditResponse 
    } from '$lib/api/api';
    import { currentResult } from '$lib/stores/stores';
    import { 
        History, 
        Clock, 
        Filter, 
        ChevronLeft, 
        ChevronRight, 
        CheckCircle2, 
        MessageSquare,
        Loader2,
        Sparkles,
        Layers,
        FileSpreadsheet,
        Search
    } from 'lucide-svelte';
    import { slide } from 'svelte/transition';

    let activeTab: 'single' | 'batch' = 'single';
    let isLoading = false;
    let isHistoryLoading = false;
    let error: string | null = null;
    let formContext = '', formPrompt = '', formResponse = '';

    let selectedProjectId: string = '';
    let selectedFilter: string = 'all';
    let searchQuery: string = '';
    let auditList: AuditSummary[] = [];
    let totalAudits = 0;
    let currentPage = 1;
    let pageSize = 20;

    $: totalPages = Math.ceil(totalAudits / pageSize) || 1;
    $: filteredAuditList = auditList.filter(item => {
        if (!searchQuery.trim()) return true;
        const q = searchQuery.toLowerCase().trim();
        return (item.prompt && item.prompt.toLowerCase().includes(q)) ||
               (item.response && item.response.toLowerCase().includes(q));
    });

    async function loadHistory(page = 1) {
        isHistoryLoading = true;
        try {
            const filterLabel = selectedFilter === 'all' ? undefined : selectedFilter;
            const res = await fetchAuditHistory(page, pageSize, selectedProjectId || undefined, filterLabel);
            auditList = res.items;
            totalAudits = res.total;
            currentPage = res.page;
        } catch (e: any) {
            console.warn('Lỗi tải lịch sử:', e);
        } finally {
            isHistoryLoading = false;
        }
    }

    onMount(() => {
        loadHistory(1);
    });

    function handleProjectChange(event: CustomEvent<string>) {
        selectedProjectId = event.detail;
        loadHistory(1);
    }

    function handleFilterChange(label: string) {
        selectedFilter = label;
        loadHistory(1);
    }

    async function handleAnalysis(event: CustomEvent) {
        isLoading = true; 
        error = null; 
        currentResult.set(null);
        try {
            const res = await submitAudit({
                context: event.detail.context,
                prompt: event.detail.prompt,
                response: event.detail.response,
                project_id: selectedProjectId || undefined,
            });
            currentResult.set(res);
            await loadHistory(1);
        } catch (e: any) {
            error = "Lỗi kết nối Server: " + e.message;
        } finally {
            isLoading = false;
        }
    }

    async function selectHistoryItem(item: AuditSummary) {
        try {
            isLoading = true;
            const detail = await fetchAuditDetail(item.id);
            formContext = detail.context;
            formPrompt = detail.prompt;
            formResponse = detail.response;
            currentResult.set(detail);
            error = null;
        } catch (e: any) {
            error = "Không thể tải chi tiết: " + e.message;
        } finally {
            isLoading = false;
        }
    }

    function resetFlow() {
        currentResult.set(null);
    }

    const getHistoryBadge = (label?: string) => {
        const l = label?.toLowerCase() || '';
        if (l.includes('no') || l.includes('entail')) 
            return { text: 'CHÍNH XÁC', css: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' };
        if (l.includes('intrinsic') || l.includes('contra')) 
            return { text: 'MÂU THUẪN', css: 'text-rose-400 border-rose-500/30 bg-rose-500/10' };
        if (l.includes('extrinsic'))
            return { text: 'BỊA ĐẶT', css: 'text-amber-400 border-amber-500/30 bg-amber-500/10' };
        return { text: 'ĐANG XỬ LÝ', css: 'text-slate-400 border-slate-500/30 bg-slate-500/10' };
    };
</script>

<div class="fixed inset-0 bg-[#030712] text-slate-200 font-sans selection:bg-indigo-500/30">
    <div class="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-10 pointer-events-none"></div>
    <div class="absolute top-0 left-0 w-full h-[500px] bg-indigo-900/10 blur-[120px] rounded-full pointer-events-none"></div>
</div>

<div class="relative z-10 h-screen flex flex-col overflow-hidden">
    <!-- Header with Workspace Selector -->
    <Header bind:selectedProjectId on:projectChange={handleProjectChange} />

    <div class="flex-1 flex overflow-hidden max-w-[1600px] mx-auto w-full px-4 gap-6 py-4">
        
        <!-- Persistent Audit History Sidebar (Connected to PostgreSQL) -->
        <aside class="w-88 hidden lg:flex flex-col bg-slate-900/30 border border-white/5 rounded-2xl backdrop-blur-md overflow-hidden shadow-2xl">
            <!-- Sidebar Header -->
            <div class="p-4 border-b border-white/5 space-y-3">
                <div class="flex items-center justify-between text-indigo-400">
                    <div class="flex items-center gap-2">
                        <History size={18} />
                        <span class="text-xs font-bold uppercase tracking-widest">Lịch Sử Đánh Giá</span>
                    </div>
                    <span class="text-[10px] bg-white/5 px-2 py-0.5 rounded-full text-slate-400 font-mono">
                        {totalAudits} kết quả
                    </span>
                </div>

                <!-- Filter Tabs -->
                <div class="flex gap-1 p-0.5 bg-slate-950/60 rounded-xl border border-white/5 text-[11px]">
                    <button 
                        on:click={() => handleFilterChange('all')}
                        class="flex-1 py-1 rounded-lg font-medium transition-all {selectedFilter === 'all' ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-400 hover:text-white'}"
                    >
                        Tất cả
                    </button>
                    <button 
                        on:click={() => handleFilterChange('no_hallucination')}
                        class="flex-1 py-1 rounded-lg font-medium transition-all {selectedFilter === 'no_hallucination' ? 'bg-emerald-600 text-white shadow-sm' : 'text-slate-400 hover:text-emerald-300'}"
                    >
                        Khớp
                    </button>
                    <button 
                        on:click={() => handleFilterChange('intrinsic')}
                        class="flex-1 py-1 rounded-lg font-medium transition-all {selectedFilter === 'intrinsic' ? 'bg-rose-600 text-white shadow-sm' : 'text-slate-400 hover:text-rose-300'}"
                    >
                        Mâu thuẫn
                    </button>
                    <button 
                        on:click={() => handleFilterChange('extrinsic')}
                        class="flex-1 py-1 rounded-lg font-medium transition-all {selectedFilter === 'extrinsic' ? 'bg-amber-600 text-white shadow-sm' : 'text-slate-400 hover:text-amber-300'}"
                    >
                        Bịa đặt
                    </button>
                </div>

                <!-- Search Input -->
                <div class="relative">
                    <Search size={13} class="absolute left-2.5 top-2.5 text-slate-500" />
                    <input 
                        type="text" 
                        bind:value={searchQuery}
                        placeholder="Tìm theo từ khóa câu hỏi..." 
                        class="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-950/70 border border-white/10 rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
                    />
                </div>
            </div>
            
            <!-- List Items -->
            <div class="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar">
                {#if isHistoryLoading}
                    <div class="flex items-center justify-center h-32 text-slate-500 gap-2 text-xs">
                        <Loader2 size={16} class="animate-spin text-indigo-400" />
                        Đang đồng bộ dữ liệu...
                    </div>
                {:else}
                    {#each filteredAuditList as item (item.id)}
                        {@const badge = getHistoryBadge(item.label)}
                        <button 
                            on:click={() => selectHistoryItem(item)}
                            class="w-full text-left p-3 rounded-xl border border-transparent bg-white/[0.02] hover:bg-white/5 hover:border-white/10 transition-all group relative overflow-hidden"
                        >
                            <div class="flex justify-between items-center mb-1.5">
                                <span class="text-[10px] font-mono text-slate-500">
                                    {new Date(item.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}
                                </span>
                                <div class="flex items-center gap-1">
                                    {#if item.has_feedback}
                                        <span title="Đã có đánh giá Human Annotation" class="text-indigo-400">
                                            <MessageSquare size={12} />
                                        </span>
                                    {/if}
                                    <span class="text-[9px] font-black px-1.5 py-0.5 rounded border {badge.css}">
                                        {badge.text}
                                    </span>
                                </div>
                            </div>
                            <p class="text-xs text-slate-300 font-medium line-clamp-2 group-hover:text-white transition-colors">
                                {item.prompt}
                            </p>
                            
                            <div class="absolute inset-y-0 left-0 w-1 bg-indigo-500 opacity-0 -translate-x-full group-hover:translate-x-0 group-hover:opacity-100 transition-all duration-300"></div>
                        </button>
                    {:else}
                        <div class="flex flex-col items-center justify-center h-40 text-slate-600 opacity-60">
                            <Clock size={24} class="mb-2" />
                            <p class="text-xs">Chưa có kết quả kiểm tra</p>
                        </div>
                    {/each}
                {/if}
            </div>

            <!-- Pagination Footer -->
            {#if totalPages > 1}
                <div class="p-3 border-t border-white/5 flex items-center justify-between text-xs text-slate-400">
                    <button 
                        disabled={currentPage <= 1}
                        on:click={() => loadHistory(currentPage - 1)}
                        class="p-1 rounded bg-white/5 hover:bg-white/10 disabled:opacity-30 disabled:pointer-events-none"
                    >
                        <ChevronLeft size={16} />
                    </button>
                    <span class="font-mono text-[11px]">Trang {currentPage} / {totalPages}</span>
                    <button 
                        disabled={currentPage >= totalPages}
                        on:click={() => loadHistory(currentPage + 1)}
                        class="p-1 rounded bg-white/5 hover:bg-white/10 disabled:opacity-30 disabled:pointer-events-none"
                    >
                        <ChevronRight size={16} />
                    </button>
                </div>
            {/if}
        </aside>

        <!-- Main Workspace Area -->
        <main class="flex-1 flex flex-col gap-5 overflow-y-auto custom-scrollbar pr-2">
            <!-- Mode Switcher Tabs -->
            <div class="flex items-center justify-between pb-2 border-b border-white/5">
                <div class="flex gap-2 p-1 bg-slate-900/50 rounded-xl border border-white/5">
                    <button 
                        on:click={() => activeTab = 'single'}
                        class="px-4 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-2 {activeTab === 'single' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-400 hover:text-white'}"
                    >
                        <Layers size={14} /> Kiểm Tra Đơn Lẻ
                    </button>
                    <button 
                        on:click={() => activeTab = 'batch'}
                        class="px-4 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-2 {activeTab === 'batch' ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-400 hover:text-white'}"
                    >
                        <FileSpreadsheet size={14} /> Đánh Giá Hàng Loạt (Batch CSV)
                    </button>
                </div>
            </div>

            {#if activeTab === 'single'}
                {#if $currentResult}
                    <div in:slide={{ duration: 300 }} class="mb-2">
                        <HalluResult result={$currentResult} on:reset={resetFlow} />
                    </div>
                {/if}

                <div class="bg-slate-900/20 border border-white/5 rounded-2xl p-6 backdrop-blur-sm transition-all duration-500 {$currentResult ? 'opacity-60 hover:opacity-100' : 'opacity-100'}">
                    <HalluForm 
                        bind:context={formContext}
                        bind:prompt={formPrompt}
                        bind:response={formResponse}
                        {isLoading} 
                        on:submit={handleAnalysis} 
                    />
                </div>

                {#if error}
                    <div class="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm text-center font-mono">
                        ⚠ {error}
                    </div>
                {/if}
            {:else}
                <div in:slide={{ duration: 300 }}>
                    <BatchEvaluation {selectedProjectId} />
                </div>
            {/if}
        </main>
    </div>
</div>

<style>
    .custom-scrollbar::-webkit-scrollbar { width: 5px; }
    .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
    .custom-scrollbar::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 10px; }
    .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #475569; }
</style>
