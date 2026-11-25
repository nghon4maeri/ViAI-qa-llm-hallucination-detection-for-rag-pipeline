<!-- applications/web/src/routes/+page.svelte -->
<script lang="ts">
    import { onMount } from 'svelte';
    import Header from '$lib/components/Header.svelte';
    import HalluForm from '$lib/components/HalluForm.svelte';
    import HalluResult from '$lib/components/HalluResult.svelte';
    import RagForm from '$lib/components/RagForm.svelte';
    import TraceView from '$lib/components/TraceView.svelte';
    import BatchEvaluation from '$lib/components/BatchEvaluation.svelte';
    import VerdictTag from '$lib/components/VerdictTag.svelte';
    import {
        submitAudit,
        submitRagAudit,
        fetchAuditHistory,
        fetchAuditDetail,
        type AuditSummary,
        type RagInput
    } from '$lib/api/api';
    import { currentResult } from '$lib/stores/stores';
    import { formatTime, pct } from '$lib/labels';
    import { ChevronLeft, ChevronRight, MessageSquare, Loader2, Search } from 'lucide-svelte';

    type Tab = 'rag' | 'single' | 'batch';
    const TABS: { id: Tab; text: string }[] = [
        { id: 'rag', text: 'Kiểm tra RAG' },
        { id: 'single', text: 'Kiểm tra đơn' },
        { id: 'batch', text: 'Bộ dữ liệu' },
    ];
    const FILTERS = [
        { id: 'all', text: 'Tất cả' },
        { id: 'no', text: 'Khớp' },
        { id: 'intrinsic', text: 'Mâu thuẫn' },
        { id: 'extrinsic', text: 'Ngoài nguồn' },
    ];

    let activeTab: Tab = 'rag';
    let isLoading = false;
    let isHistoryLoading = false;
    let error: string | null = null;
    let formContext = '', formPrompt = '', formResponse = '';
    let ragQuestion = '', ragContexts: string[] = [''], ragAnswer = '', ragGroundTruth = '';

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
    $: isRagResult = !!$currentResult?.claims?.length;

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

    async function run(task: () => Promise<any>) {
        isLoading = true;
        error = null;
        currentResult.set(null);
        try {
            currentResult.set(await task());
            await loadHistory(1);
        } catch (e: any) {
            error = 'Không kết nối được máy chủ: ' + e.message;
        } finally {
            isLoading = false;
        }
    }

    const handleAnalysis = (event: CustomEvent) =>
        run(() => submitAudit({ ...event.detail, project_id: selectedProjectId || undefined }));

    const handleRag = (event: CustomEvent<RagInput>) =>
        run(() => submitRagAudit({ ...event.detail, project_id: selectedProjectId || undefined }));

    async function selectHistoryItem(item: AuditSummary) {
        try {
            isLoading = true;
            const detail = await fetchAuditDetail(item.id);
            if (detail.contexts?.length) {
                activeTab = 'rag';
                ragQuestion = detail.prompt;
                ragContexts = [...detail.contexts];
                ragAnswer = detail.response;
                ragGroundTruth = detail.ground_truth ?? '';
            } else {
                activeTab = 'single';
                formContext = detail.context;
                formPrompt = detail.prompt;
                formResponse = detail.response;
            }
            currentResult.set(detail);
            error = null;
        } catch (e: any) {
            error = 'Không tải được chi tiết: ' + e.message;
        } finally {
            isLoading = false;
        }
    }

    function resetFlow() {
        currentResult.set(null);
    }

    function switchTab(tab: Tab) {
        activeTab = tab;
        // A result belongs to the tab that produced it
        if ((tab === 'rag') !== isRagResult) currentResult.set(null);
    }
</script>

<div class="flex h-screen flex-col">
    <Header bind:selectedProjectId on:projectChange={handleProjectChange} />

    <div class="flex min-h-0 flex-1">
        <!-- History -->
        <aside class="hidden w-[280px] shrink-0 flex-col border-r border-line bg-page lg:flex">
            <div class="space-y-3 px-4 pt-6 pb-3">
                <div class="flex items-baseline justify-between">
                    <h2 class="text-sm font-medium">Lịch sử</h2>
                    <span class="font-mono text-xs text-ink-3 tabular-nums">{totalAudits}</span>
                </div>

                <div class="flex flex-wrap gap-1" role="tablist" aria-label="Lọc theo kết luận">
                    {#each FILTERS as f}
                        <button
                            type="button"
                            role="tab"
                            aria-selected={selectedFilter === f.id}
                            on:click={() => handleFilterChange(f.id)}
                            class="h-7 whitespace-nowrap rounded-md px-2 text-xs transition-colors duration-150 {selectedFilter === f.id ? 'bg-raised text-ink' : 'text-ink-2 hover:text-ink'}"
                        >{f.text}</button>
                    {/each}
                </div>

                <label class="relative block">
                    <span class="sr-only">Tìm trong lịch sử</span>
                    <Search size={16} strokeWidth={1.5} class="absolute top-2 left-2.5 text-ink-3" />
                    <input
                        type="text"
                        bind:value={searchQuery}
                        placeholder="Tìm câu hỏi"
                        class="h-8 w-full rounded-lg border border-line-strong bg-card pr-3 pl-8 text-[13px] placeholder:text-ink-3 focus:border-accent focus:outline-none"
                    />
                </label>
            </div>

            <div class="flex-1 space-y-0.5 overflow-y-auto px-2 pb-4">
                {#if isHistoryLoading}
                    <div class="flex items-center gap-2 px-2 py-6 text-[13px] text-ink-3">
                        <Loader2 size={16} strokeWidth={1.5} class="animate-spin" /> Đang tải
                    </div>
                {:else}
                    {#each filteredAuditList as item (item.id)}
                        <button
                            type="button"
                            on:click={() => selectHistoryItem(item)}
                            class="w-full rounded-lg px-2 py-2 text-left transition-colors duration-150 hover:bg-raised {$currentResult?.id === item.id ? 'bg-raised' : ''}"
                        >
                            <p class="line-clamp-2 text-[13px] leading-5">{item.prompt}</p>
                            <div class="mt-1 flex items-center justify-between gap-2 text-xs">
                                <VerdictTag label={item.label} />
                                <span class="flex items-center gap-2 font-mono text-ink-3 tabular-nums">
                                    {#if item.has_feedback}
                                        <span title="Đã có đánh giá của người duyệt"><MessageSquare size={14} strokeWidth={1.5} /></span>
                                    {/if}
                                    {#if item.faithfulness !== null && item.faithfulness !== undefined}
                                        <span title="Độ bám nguồn">{pct(item.faithfulness)}</span>
                                    {/if}
                                    {formatTime(item.created_at)}
                                </span>
                            </div>
                        </button>
                    {:else}
                        <p class="px-2 py-6 text-[13px] text-ink-3">Chưa có lượt kiểm tra nào</p>
                    {/each}
                {/if}
            </div>

            {#if totalPages > 1}
                <div class="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-ink-2">
                    <button
                        type="button"
                        disabled={currentPage <= 1}
                        on:click={() => loadHistory(currentPage - 1)}
                        class="rounded-md p-1 hover:bg-raised disabled:opacity-30"
                        aria-label="Trang trước"
                    ><ChevronLeft size={16} strokeWidth={1.5} /></button>
                    <span class="font-mono tabular-nums">{currentPage}/{totalPages}</span>
                    <button
                        type="button"
                        disabled={currentPage >= totalPages}
                        on:click={() => loadHistory(currentPage + 1)}
                        class="rounded-md p-1 hover:bg-raised disabled:opacity-30"
                        aria-label="Trang sau"
                    ><ChevronRight size={16} strokeWidth={1.5} /></button>
                </div>
            {/if}
        </aside>

        <!-- Workspace -->
        <main class="min-w-0 flex-1 overflow-y-auto">
            <div class="mx-auto max-w-[1200px] space-y-6 px-6 py-6 lg:px-8">
                <nav class="flex gap-1 border-b border-line" aria-label="Chế độ kiểm tra">
                    {#each TABS as tab}
                        <button
                            type="button"
                            on:click={() => switchTab(tab.id)}
                            aria-current={activeTab === tab.id ? 'page' : undefined}
                            class="-mb-px h-10 border-b-2 px-3 text-[14px] transition-colors duration-150 {activeTab === tab.id ? 'border-accent text-ink' : 'border-transparent text-ink-2 hover:text-ink'}"
                        >{tab.text}</button>
                    {/each}
                </nav>

                {#if error}
                    <p class="rounded-lg bg-bad-mark px-4 py-3 text-[13px] text-bad" role="alert">{error}</p>
                {/if}

                {#if activeTab === 'rag'}
                    {#if $currentResult && isRagResult}
                        <TraceView result={$currentResult} on:reset={resetFlow} />
                    {/if}
                    <section class="rounded-xl border border-line bg-card p-6">
                        <RagForm
                            bind:question={ragQuestion}
                            bind:contexts={ragContexts}
                            bind:answer={ragAnswer}
                            bind:groundTruth={ragGroundTruth}
                            {isLoading}
                            on:submit={handleRag}
                        />
                    </section>
                {:else if activeTab === 'single'}
                    {#if $currentResult && !isRagResult}
                        <HalluResult result={$currentResult} on:reset={resetFlow} />
                    {/if}
                    <section class="rounded-xl border border-line bg-card p-6">
                        <HalluForm
                            bind:context={formContext}
                            bind:prompt={formPrompt}
                            bind:response={formResponse}
                            {isLoading}
                            on:submit={handleAnalysis}
                        />
                    </section>
                {:else}
                    <BatchEvaluation {selectedProjectId} />
                {/if}

                <p class="text-xs text-ink-3">
                    ViAI-QA đánh giá câu trả lời của hệ thống RAG so với tài liệu được cung cấp, không thay thế tư vấn y khoa.
                </p>
            </div>
        </main>
    </div>
</div>
