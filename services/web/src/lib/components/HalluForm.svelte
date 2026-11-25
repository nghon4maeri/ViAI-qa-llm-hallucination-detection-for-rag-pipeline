<!-- services/web/src/lib/components/HalluForm.svelte -->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { Loader2 } from 'lucide-svelte';

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
            title: 'Khớp nguồn',
            context: 'Thời điểm dùng thuốc: uống ngay trước hoặc trong bữa ăn. Lưu ý: Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy.',
            prompt: 'Uống thuốc Comiaryl đúng cách như thế nào?',
            response: 'Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy.'
        },
        {
            title: 'Mâu thuẫn',
            context: 'Thuốc Paracetamol hạ sốt cho người lớn dùng liều 500mg đến 1000mg mỗi lần, cách nhau tối thiểu 4 đến 6 giờ, tuyệt đối không uống quá 4000mg mỗi ngày vì nguy cơ suy gan cấp.',
            prompt: 'Tôi có thể uống Paracetamol 6000mg mỗi ngày được không?',
            response: 'Bạn hoàn toàn có thể uống 6000mg Paracetamol mỗi ngày để hạ sốt nhanh chóng hơn mà không gây hại cho gan.'
        },
        {
            title: 'Ngoài nguồn',
            context: 'Vitamin D3 Aquadetrim nên được bảo quản ở những nơi khô ráo, thoáng mát, tránh ánh nắng trực tiếp.',
            prompt: 'Bảo quản Vitamin D3 Aquadetrim thế nào?',
            response: 'Bảo quản thuốc ở nơi khô ráo, thoáng mát. Sau khi mở nắp, thuốc chỉ dùng được trong 7 ngày.'
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

    const field = 'w-full rounded-lg border border-line-strong bg-card px-3 py-2 text-[14px] leading-6 placeholder:text-ink-3 resize-y transition-colors duration-150 focus:border-accent focus:outline-none';
</script>

<form class="space-y-6" on:submit|preventDefault={handleSubmit}>
    <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] text-ink-2">Ví dụ</span>
        {#each PRESETS as p}
            <button
                type="button"
                on:click={() => applyPreset(p)}
                class="h-8 rounded-lg border border-line-strong bg-card px-3 text-[13px] transition-colors duration-150 hover:bg-raised"
            >{p.title}</button>
        {/each}
        {#if context || prompt || response}
            <button
                type="button"
                on:click={clearForm}
                class="h-8 rounded-lg px-3 text-[13px] text-ink-2 transition-colors duration-150 hover:bg-raised hover:text-ink"
            >Xoá</button>
        {/if}
    </div>

    <label class="block space-y-2">
        <span class="text-[13px] font-medium">Tài liệu nguồn</span>
        <textarea bind:value={context} rows="5" class={field} placeholder="Đoạn văn bản chứa thông tin chuẩn"></textarea>
    </label>

    <div class="grid gap-6 md:grid-cols-2">
        <label class="block space-y-2">
            <span class="text-[13px] font-medium">Câu hỏi của người dùng</span>
            <textarea bind:value={prompt} rows="4" class={field} placeholder="Câu hỏi gửi tới chatbot"></textarea>
        </label>
        <label class="block space-y-2">
            <span class="text-[13px] font-medium">Câu trả lời của chatbot</span>
            <textarea bind:value={response} rows="4" class={field} placeholder="Câu trả lời cần kiểm định"></textarea>
        </label>
    </div>

    <button
        type="submit"
        disabled={isLoading || !context || !prompt || !response}
        class="inline-flex h-11 items-center gap-2 rounded-lg bg-accent px-5 text-[14px] font-medium text-on-accent transition-[background-color,transform] duration-150 hover:bg-accent-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
    >
        {#if isLoading}
            <Loader2 size={16} strokeWidth={1.5} class="animate-spin" /> Đang kiểm định
        {:else}
            Kiểm định câu trả lời
        {/if}
    </button>
</form>
