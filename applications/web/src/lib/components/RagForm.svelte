<!-- applications/web/src/lib/components/RagForm.svelte -->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { Plus, X, Loader2 } from 'lucide-svelte';

	export let isLoading = false;
	export let question = '';
	export let contexts: string[] = [''];
	export let answer = '';
	export let groundTruth = '';

	const dispatch = createEventDispatcher();

	$: filled = contexts.filter((c) => c.trim());
	$: canSubmit = question.trim() && answer.trim() && filled.length > 0 && !isLoading;

	const PRESETS = [
		{
			title: 'Cách dùng thuốc',
			question: 'Uống thuốc Comiaryl đúng cách như thế nào?',
			contexts: [
				'Thời điểm dùng thuốc: uống ngay trước hoặc trong bữa ăn. Lưu ý: Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy.',
				'Comiaryl chống chỉ định với người suy gan nặng, suy thận nặng và phụ nữ có thai.'
			],
			answer:
				'Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy. Thuốc nên uống ngay trước hoặc trong bữa ăn. Người bị suy gan nhẹ cần tăng gấp đôi liều.',
			groundTruth: 'Nên uống nguyên viên thuốc Comiaryl với một cốc nước đầy.'
		},
		{
			title: 'Liều tối đa',
			question: 'Người lớn được uống tối đa bao nhiêu Paracetamol mỗi ngày?',
			contexts: [
				'Paracetamol hạ sốt cho người lớn dùng liều 500mg đến 1000mg mỗi lần, cách nhau tối thiểu 4 đến 6 giờ.',
				'Không uống quá 4000mg Paracetamol mỗi ngày vì nguy cơ suy gan cấp.'
			],
			answer:
				'Người lớn có thể uống tới 6000mg Paracetamol mỗi ngày. Mỗi lần uống cách nhau tối thiểu 4 đến 6 giờ.',
			groundTruth: ''
		}
	];

	function applyPreset(p: (typeof PRESETS)[number]) {
		question = p.question;
		contexts = [...p.contexts];
		answer = p.answer;
		groundTruth = p.groundTruth;
	}

	function submit() {
		if (!canSubmit) return;
		dispatch('submit', {
			question,
			contexts: filled,
			answer,
			ground_truth: groundTruth || undefined
		});
	}

	const field =
		'w-full rounded-lg border border-line-strong bg-card px-3 py-2 text-[14px] leading-6 placeholder:text-ink-3 transition-colors duration-150 focus:border-accent focus:outline-none';
</script>

<form class="space-y-6" on:submit|preventDefault={submit}>
	<div class="flex flex-wrap items-center gap-2">
		<span class="text-[13px] text-ink-2">Ví dụ</span>
		{#each PRESETS as p (p.title)}
			<button
				type="button"
				on:click={() => applyPreset(p)}
				class="h-8 rounded-lg border border-line-strong bg-card px-3 text-[13px] transition-colors duration-150 hover:bg-raised"
				>{p.title}</button
			>
		{/each}
	</div>

	<label class="block space-y-2">
		<span class="text-[13px] font-medium">Câu hỏi của người dùng</span>
		<input bind:value={question} class="{field} h-10" placeholder="Câu hỏi gửi tới chatbot" />
	</label>

	<fieldset class="space-y-3">
		<legend class="mb-2 text-[13px] font-medium">Tài liệu truy xuất</legend>
		{#each contexts, i (i)}
			<div class="flex gap-3">
				<span class="w-8 pt-2 font-mono text-xs text-ink-3">[{i + 1}]</span>
				<textarea
					bind:value={contexts[i]}
					rows="3"
					class="{field} resize-y"
					placeholder="Đoạn văn bản mà retriever trả về"
					aria-label="Tài liệu {i + 1}"
				></textarea>
				<button
					type="button"
					on:click={() => (contexts = contexts.filter((__, j) => j !== i))}
					disabled={contexts.length === 1}
					class="mt-1 size-8 shrink-0 rounded-lg text-ink-3 transition-colors duration-150 hover:bg-raised hover:text-ink disabled:invisible"
					aria-label="Xoá tài liệu {i + 1}"
				>
					<X size={16} strokeWidth={1.5} class="mx-auto" />
				</button>
			</div>
		{/each}
		<button
			type="button"
			on:click={() => (contexts = [...contexts, ''])}
			disabled={contexts.length >= 20}
			class="ml-11 inline-flex h-8 items-center gap-2 rounded-lg px-2 text-[13px] text-accent transition-colors duration-150 hover:bg-accent-soft"
		>
			<Plus size={16} strokeWidth={1.5} /> Thêm tài liệu
		</button>
	</fieldset>

	<label class="block space-y-2">
		<span class="text-[13px] font-medium">Câu trả lời của chatbot</span>
		<textarea
			bind:value={answer}
			rows="4"
			class="{field} resize-y"
			placeholder="Câu trả lời cần kiểm định, mỗi câu được chấm riêng"
		></textarea>
	</label>

	<details class="group">
		<summary
			class="cursor-pointer text-[13px] text-ink-2 transition-colors duration-150 hover:text-ink"
		>
			Đáp án chuẩn (không bắt buộc, để tính độ phủ)
		</summary>
		<textarea
			bind:value={groundTruth}
			rows="2"
			class="{field} mt-2 resize-y"
			placeholder="Câu trả lời đúng do chuyên gia viết"
		></textarea>
	</details>

	<button
		type="submit"
		disabled={!canSubmit}
		class="inline-flex h-11 items-center gap-2 rounded-lg bg-accent px-5 text-[14px] font-medium text-on-accent transition-[background-color,transform] duration-150 hover:bg-accent-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
	>
		{#if isLoading}
			<Loader2 size={16} strokeWidth={1.5} class="animate-spin" /> Đang chấm từng câu
		{:else}
			Kiểm tra câu trả lời
		{/if}
	</button>
</form>
