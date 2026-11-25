<!-- applications/web/src/lib/components/FeedbackPanel.svelte -->
<script lang="ts">
	import { Check } from 'lucide-svelte';
	import type { AuditResponse } from '$lib/api/api';
	import { submitFeedback } from '$lib/api/api';
	import { errorMessage, labelMeta } from '$lib/labels';

	export let result: AuditResponse;

	let comment = '';
	let isSubmitting = false;
	let error = '';

	// Corrected labels use the model's own vocabulary so feedback can feed retraining directly
	const OPTIONS = [
		{ value: 'CORRECT', text: 'Kết quả đúng' },
		{ value: 'no', text: `Thực ra là ${labelMeta('no').short.toLowerCase()}` },
		{ value: 'intrinsic', text: `Thực ra là ${labelMeta('intrinsic').short.toLowerCase()}` },
		{ value: 'extrinsic', text: `Thực ra là ${labelMeta('extrinsic').short.toLowerCase()}` }
	];

	async function send(value: string) {
		isSubmitting = true;
		error = '';
		try {
			result.feedback = await submitFeedback(result.id, {
				feedback_label: value,
				corrected_label: value === 'CORRECT' ? result.label : value,
				comment: comment || undefined
			});
		} catch (e) {
			error = errorMessage(e, 'Không gửi được phản hồi');
		} finally {
			isSubmitting = false;
		}
	}
</script>

<section class="rounded-xl border border-line bg-card p-5">
	<div class="flex items-center justify-between gap-4">
		<h3 class="text-sm font-medium">Đánh giá của người duyệt</h3>
		{#if result.feedback}
			<span class="inline-flex items-center gap-1.5 text-[13px] text-ok">
				<Check size={16} strokeWidth={1.5} /> Đã lưu
			</span>
		{/if}
	</div>

	{#if result.feedback}
		<p class="mt-2 text-[13px] text-ink-2">
			Nhãn đúng: <span class="text-ink">{labelMeta(result.feedback.corrected_label).short}</span>
			{#if result.feedback.comment}· {result.feedback.comment}{/if}
		</p>
	{:else}
		<p class="mt-1 text-[13px] text-ink-2">Nhãn bạn sửa được lưu lại để huấn luyện lại mô hình</p>
		<div class="mt-4 flex flex-wrap gap-2">
			{#each OPTIONS as opt (opt.value)}
				<button
					type="button"
					disabled={isSubmitting}
					on:click={() => send(opt.value)}
					class="h-8 rounded-lg border border-line-strong bg-card px-3 text-[13px] transition-colors duration-150 hover:bg-raised disabled:opacity-50"
				>
					{opt.text}
				</button>
			{/each}
		</div>
		<label class="mt-3 block">
			<span class="sr-only">Ghi chú</span>
			<input
				type="text"
				bind:value={comment}
				placeholder="Ghi chú, ví dụ câu nào gây nhầm"
				class="h-9 w-full rounded-lg border border-line-strong bg-card px-3 text-[13px] placeholder:text-ink-3"
			/>
		</label>
		{#if error}
			<p class="mt-2 text-[13px] text-bad">{error}</p>
		{/if}
	{/if}
</section>
