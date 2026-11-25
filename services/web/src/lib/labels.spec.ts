import { describe, it, expect } from 'vitest';
import { labelMeta, pct } from './labels';

describe('labelMeta', () => {
    it('maps backend labels to verdict wording and tone', () => {
        expect(labelMeta('no').tone).toBe('ok');
        expect(labelMeta('INTRINSIC').short).toBe('Mâu thuẫn');
        expect(labelMeta('extrinsic').tone).toBe('warn');
    });

    it('falls back to a neutral state for unknown or pending labels', () => {
        expect(labelMeta(null).tone).toBe('idle');
        expect(labelMeta('no_hallucination').tone).toBe('idle');
    });
});

describe('pct', () => {
    it('shows a dash instead of 0% when a metric is missing', () => {
        expect(pct(null)).toBe('—');
        expect(pct(undefined)).toBe('—');
        expect(pct(0)).toBe('0%');
        expect(pct(0.8638, 1)).toBe('86.4%');
    });
});
