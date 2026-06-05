import type {
	ScoreTransactionRequest,
	ScoreTransactionResponse,
	HealthResponse,
	ErrorResponse,
	UpdateModeResponse,
	LookupModeResponse,
	InsertModeResponse,
	UpdateMode,
	InsertMode
} from './types';

const API_BASE = '/api';

export class ApiError extends Error {
	constructor(
		public status: number,
		public error: string,
		message: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

async function handleResponse<T>(response: Response): Promise<T> {
	if (!response.ok) {
		let errorData: ErrorResponse;
		try {
			const data = await response.json();
			errorData = data.detail || data;
		} catch {
			errorData = {
				error: 'unknown_error',
				message: `HTTP ${response.status}: ${response.statusText}`
			};
		}
		throw new ApiError(response.status, errorData.error, errorData.message);
	}
	return response.json();
}

export async function scoreTransaction(
	request: ScoreTransactionRequest
): Promise<ScoreTransactionResponse> {
	const response = await fetch(`${API_BASE}/score-transaction`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(request)
	});
	return handleResponse<ScoreTransactionResponse>(response);
}

export async function checkHealth(): Promise<HealthResponse> {
	const response = await fetch(`${API_BASE}/health`);
	return handleResponse<HealthResponse>(response);
}

// ---- Config Mode Toggles ----

export async function getUpdateMode(): Promise<UpdateModeResponse> {
	const response = await fetch(`${API_BASE}/config/update-mode`);
	return handleResponse(response);
}

export async function setUpdateMode(mode: UpdateMode): Promise<UpdateModeResponse> {
	const response = await fetch(`${API_BASE}/config/update-mode/${mode}`, { method: 'POST' });
	return handleResponse(response);
}

export async function getLookupMode(): Promise<LookupModeResponse> {
	const response = await fetch(`${API_BASE}/config/lookup-mode`);
	return handleResponse(response);
}

export async function setLookupMode(mode: 'memory' | 'db'): Promise<LookupModeResponse> {
	const response = await fetch(`${API_BASE}/config/lookup-mode/${mode}`, { method: 'POST' });
	return handleResponse(response);
}

export async function getInsertMode(): Promise<InsertModeResponse> {
	const response = await fetch(`${API_BASE}/config/insert-mode`);
	return handleResponse(response);
}

export async function setInsertMode(mode: InsertMode): Promise<InsertModeResponse> {
	const response = await fetch(`${API_BASE}/config/insert-mode/${mode}`, { method: 'POST' });
	return handleResponse(response);
}

// ---- Mock data API functions ----

export async function getMockCustomer(): Promise<import('./types').MockCustomer> {
	const response = await fetch(`${API_BASE}/mock/customer`);
	return handleResponse(response);
}

export async function getMockTransaction(
	fraudType?: import('./types').FraudType
): Promise<import('./types').MockTransaction> {
	const url = fraudType
		? `${API_BASE}/mock/transaction?fraud_type=${fraudType}`
		: `${API_BASE}/mock/transaction`;
	const response = await fetch(url);
	return handleResponse(response);
}

export async function getFraudTypes(): Promise<string[]> {
	const response = await fetch(`${API_BASE}/mock/fraud-types`);
	return handleResponse(response);
}

// ---- Load Testing API functions ----

export interface LoadTestConfig {
	target_tps: number;
	duration_seconds: number;
	concurrency: number;
	fraud_rate: number;
	target_url?: string;
}

export interface RecentTransaction {
	customer_id: string;
	amount: number;
	channel: string;
	risk_level: string;
	latency_ms: number;
	scoring_ms: number;
	persist_ms: number;
	timestamp: string;
}

export interface LoadTestProgress {
	test_id: string;
	status: string;
	elapsed_seconds: number;
	total_transactions: number;
	successful: number;
	failed: number;
	current_tps: number;
	avg_latency_ms: number;
	avg_scoring_ms: number;
	avg_persist_ms: number;
	p95_latency_ms: number;
	p99_latency_ms: number;
	risk_distribution: Record<string, number>;
	recent_transactions: RecentTransaction[];
	error_message?: string;
}

export interface LoadTestResult {
	test_id: string;
	config: LoadTestConfig;
	status: string;
	start_time: string;
	end_time: string;
	duration_seconds: number;
	total_transactions: number;
	successful: number;
	failed: number;
	error_rate: number;
	throughput_tps: number;
	avg_latency_ms: number;
	min_latency_ms: number;
	max_latency_ms: number;
	p50_latency_ms: number;
	p95_latency_ms: number;
	p99_latency_ms: number;
	risk_distribution: Record<string, number>;
	latency_histogram: Array<{ bucket_ms: string; count: number; percentage: number }>;
}


export async function startLoadTest(config: LoadTestConfig): Promise<LoadTestProgress> {
	const response = await fetch(`${API_BASE}/loadtest/start`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(config)
	});
	return handleResponse(response);
}

export async function getLoadTestProgress(testId: string): Promise<LoadTestProgress> {
	const response = await fetch(`${API_BASE}/loadtest/progress/${testId}`);
	return handleResponse(response);
}

export async function getLoadTestResult(testId: string): Promise<LoadTestResult> {
	const response = await fetch(`${API_BASE}/loadtest/result/${testId}`);
	return handleResponse(response);
}

export async function stopLoadTest(testId: string): Promise<void> {
	const response = await fetch(`${API_BASE}/loadtest/stop/${testId}`, { method: 'POST' });
	return handleResponse(response);
}

// ---- Locust External Load Test API (proxied through FastAPI) ----

export type LocustTarget = 'local' | 'bastion';

export interface LocustStartRequest {
	user_count: number;
	spawn_rate: number;
	host?: string;
	target: LocustTarget;
}

export interface LocustStatus {
	available: boolean;
	state: string;
	user_count: number;
	workers: number;
	message: string;
}

export interface LocustStats {
	state: string;
	user_count: number;
	total_requests: number;
	total_failures: number;
	current_rps: number;
	current_fail_rate: number;
	avg_response_time: number;
	min_response_time: number;
	max_response_time: number;
	p50_response_time: number;
	p90_response_time: number;
	p95_response_time: number;
	p99_response_time: number;
	error_messages: string[];
}

export async function getLocustStatus(target: LocustTarget = 'local'): Promise<LocustStatus> {
	const response = await fetch(`${API_BASE}/loadtest/external/status?target=${target}`);
	return handleResponse(response);
}

export interface LocustStartResponse {
	success: boolean;
	test_id: string;
	message: string;
	details?: unknown;
}

export async function startLocustTest(config: LocustStartRequest): Promise<LocustStartResponse> {
	const response = await fetch(`${API_BASE}/loadtest/external/start`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(config)
	});
	return handleResponse(response);
}

export async function stopLocustTest(target: LocustTarget = 'local'): Promise<{ success: boolean; message: string }> {
	const response = await fetch(`${API_BASE}/loadtest/external/stop?target=${target}`);
	return handleResponse(response);
}

export async function getLocustStats(target: LocustTarget = 'local'): Promise<LocustStats> {
	const response = await fetch(`${API_BASE}/loadtest/external/stats?target=${target}`);
	return handleResponse(response);
}

export async function resetLocustStats(target: LocustTarget = 'local'): Promise<{ success: boolean; message: string }> {
	const response = await fetch(`${API_BASE}/loadtest/external/reset?target=${target}`);
	return handleResponse(response);
}

export interface ActiveLocustTest {
	active: boolean;
	test_id: string | null;
	start_time?: string;
	config?: {
		user_count: number;
		spawn_rate: number;
		host?: string;
	};
	message?: string;
}

export async function getActiveLocustTest(): Promise<ActiveLocustTest> {
	const response = await fetch(`${API_BASE}/loadtest/external/active-test`);
	return handleResponse(response);
}

// Legacy bastion functions (deprecated - use Locust proxy instead)
export interface BastionStartRequest {
	target_tps: number;
	duration_seconds: number;
	concurrency: number;
	fraud_rate: number;
	target_url?: string;
}

export interface BastionStartResponse {
	test_id: string;
	status: string;
	message: string;
	target_url: string;
	config: BastionStartRequest;
}

export async function startBastionLoadTest(
	bastionUrl: string,
	config: BastionStartRequest
): Promise<BastionStartResponse> {
	const response = await fetch(`${bastionUrl}/start`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(config)
	});
	return handleResponse(response);
}

export async function stopBastionLoadTest(bastionUrl: string, testId: string): Promise<void> {
	const response = await fetch(`${bastionUrl}/stop/${testId}`, { method: 'POST' });
	return handleResponse(response);
}
