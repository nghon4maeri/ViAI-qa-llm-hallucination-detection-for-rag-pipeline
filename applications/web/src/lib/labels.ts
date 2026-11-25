// applications/web/src/lib/labels.ts
// One place for verdict wording and colour, shared by history, results, trace view and batches.
export type Tone = 'ok' | 'bad' | 'warn' | 'idle';

export interface LabelMeta {
    short: string;
    long: string;
    tone: Tone;
}

const META: Record<string, LabelMeta> = {
    no: { short: 'Khớp nguồn', long: 'Khớp với tài liệu nguồn', tone: 'ok' },
    intrinsic: { short: 'Mâu thuẫn', long: 'Mâu thuẫn với tài liệu nguồn', tone: 'bad' },
    extrinsic: { short: 'Ngoài nguồn', long: 'Có thông tin không nằm trong tài liệu', tone: 'warn' },
};

export function labelMeta(label?: string | null): LabelMeta {
    return META[(label || '').toLowerCase()] ?? { short: 'Đang xử lý', long: 'Đang xử lý', tone: 'idle' };
}

export const TONE_TEXT: Record<Tone, string> = {
    ok: 'text-ok',
    bad: 'text-bad',
    warn: 'text-warn',
    idle: 'text-ink-3',
};

export const TONE_DOT: Record<Tone, string> = {
    ok: 'bg-ok',
    bad: 'bg-bad',
    warn: 'bg-warn',
    idle: 'bg-ink-3',
};

export const pct = (v?: number | null, digits = 0) =>
    v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`;

export const formatTime = (iso: string) =>
    new Date(iso).toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
