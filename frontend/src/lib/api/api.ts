// frontend/src/lib/api/api.ts

export interface HalluInput {
    context: string;
    prompt: string;
    response: string;
    project_id?: string;
}

export interface EvaluationBreakdown {
    nli_entailment?: number | null;
    nli_neutral?: number | null;
    nli_contradiction?: number | null;
    ner_overlap_ratio?: number | null;
    ner_new_entity_count?: number | null;
    llm_uncertainty?: number | null;
    active_guardrail?: string | null;
}

export interface FeedbackInput {
    feedback_label: string;
    corrected_label?: string;
    comment?: string;
}

export interface FeedbackResponse {
    id: string;
    audit_run_id: string;
    feedback_label: string;
    corrected_label?: string | null;
    comment?: string | null;
    created_at: string;
    updated_at: string;
}

export interface Project {
    id: string;
    name: string;
    slug: string;
    description?: string | null;
    is_default: boolean;
    created_at: string;
}

export interface AuditResponse {
    id: string;
    project_id: string;
    status: string;
    label: string;
    confidence: number;
    breakdown?: EvaluationBreakdown | null;
    context: string;
    prompt: string;
    response: string;
    model_version: string;
    error_code?: string | null;
    error_message?: string | null;
    latency_ms?: number | null;
    feedback?: FeedbackResponse | null;
    created_at: string;
    completed_at?: string | null;
}

export interface HalluOutput {
    label: string;
    confidence: number;
    id?: string;
    breakdown?: EvaluationBreakdown | null;
    latency_ms?: number | null;
    feedback?: FeedbackResponse | null;
}

export interface AuditSummary {
    id: string;
    project_id: string;
    prompt: string;
    response: string;
    label: string;
    confidence: number;
    status: string;
    has_feedback: boolean;
    created_at: string;
}

export interface AuditListResponse {
    items: AuditSummary[];
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
}

export interface BatchUploadResponse {
    batch_id: string;
    project_id: string;
    filename: string;
    total_count: number;
    status: string;
    message: string;
}

export interface BatchItemResult {
    id: string;
    prompt: string;
    response: string;
    label?: string | null;
    confidence?: number | null;
    status: string;
    latency_ms?: number | null;
    created_at: string;
}

export interface BatchDetailResponse {
    id: string;
    project_id: string;
    filename: string;
    status: string;
    total_count: number;
    completed_count: number;
    failed_count: number;
    hallucination_count: number;
    hallucination_rate: number;
    items: BatchItemResult[];
    created_at: string;
    completed_at?: string | null;
}

const API_BASE = (import.meta.env?.VITE_API_URL || '').replace(/\/$/, '');
const AUDITS_URL = `${API_BASE}/api/v1/audits`;
const PROJECTS_URL = `${API_BASE}/api/v1/projects`;
const BATCHES_URL = `${API_BASE}/api/v1/batches`;

const DEFAULT_HEADERS: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-API-Key': 'vihallu-dev-key-local',
};

export const submitAudit = async (
    data: HalluInput
): Promise<AuditResponse> => {
    const res = await fetch(AUDITS_URL, {
        method: "POST",
        headers: DEFAULT_HEADERS,
        body: JSON.stringify({
            context: data.context,
            prompt: data.prompt,
            response: data.response,
            project_id: data.project_id || undefined,
        }),
    });

    if (!res.ok) {
        const errorBody = await res.json().catch(() => ({}));
        throw new Error(errorBody.detail || `Lỗi hệ thống (${res.status})`);
    }
    return await res.json();
};

export const fetchAuditHistory = async (
    page: number = 1,
    pageSize: number = 20,
    projectId?: string,
    label?: string
): Promise<AuditListResponse> => {
    const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
    });
    if (projectId) params.append('project_id', projectId);
    if (label && label !== 'all') params.append('label', label);

    const res = await fetch(`${AUDITS_URL}?${params.toString()}`, {
        method: 'GET',
        headers: DEFAULT_HEADERS,
    });

    if (!res.ok) {
        throw new Error(`Không thể lấy lịch sử audit (${res.status})`);
    }
    return await res.json();
};

export const fetchAuditDetail = async (auditId: string): Promise<AuditResponse> => {
    const res = await fetch(`${AUDITS_URL}/${auditId}`, {
        method: 'GET',
        headers: DEFAULT_HEADERS,
    });

    if (!res.ok) {
        throw new Error(`Không thể lấy chi tiết audit (${res.status})`);
    }
    return await res.json();
};

export const submitFeedback = async (
    auditId: string,
    feedback: FeedbackInput
): Promise<FeedbackResponse> => {
    const res = await fetch(`${AUDITS_URL}/${auditId}/feedback`, {
        method: 'POST',
        headers: DEFAULT_HEADERS,
        body: JSON.stringify(feedback),
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Không thể gửi phản hồi (${res.status})`);
    }
    return await res.json();
};

export const fetchProjects = async (): Promise<Project[]> => {
    const res = await fetch(PROJECTS_URL, {
        method: 'GET',
        headers: DEFAULT_HEADERS,
    });

    if (!res.ok) {
        throw new Error(`Không thể lấy danh sách projects (${res.status})`);
    }
    return await res.json();
};

export const uploadBatchCsv = async (
    file: File,
    projectId?: string
): Promise<BatchUploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    if (projectId) {
        formData.append('project_id', projectId);
    }

    const res = await fetch(`${BATCHES_URL}/upload`, {
        method: 'POST',
        headers: {
            'X-API-Key': 'vihallu-dev-key-local',
        },
        body: formData,
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Lỗi tải lên file CSV (${res.status})`);
    }
    return await res.json();
};

export const fetchBatchStatus = async (batchId: string): Promise<BatchDetailResponse> => {
    const res = await fetch(`${BATCHES_URL}/${batchId}`, {
        method: 'GET',
        headers: DEFAULT_HEADERS,
    });

    if (!res.ok) {
        throw new Error(`Không thể lấy trạng thái batch (${res.status})`);
    }
    return await res.json();
};

export const getBatchExportUrl = (batchId: string): string => {
    return `${BATCHES_URL}/${batchId}/export`;
};

/**
 * Backward-compatible wrapper for existing components
 */
export const detectHallucination = async (data: HalluInput): Promise<AuditResponse> => {
    return submitAudit(data);
};
