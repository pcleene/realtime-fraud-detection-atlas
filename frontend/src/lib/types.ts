// V2 types aligned with backend_v2 models

export type RiskLevel = 'low' | 'medium' | 'high';
export type Channel = 'Livin' | 'KOPRA' | 'ATM' | 'QRIS' | 'Branch' | 'Ecom';

// ---- V2 Request ----

export interface ScoreTransactionRequest {
	customer_id: string;
	b1?: string;           // source account
	b2: string;            // destination account
	c2?: string;           // destination name
	d2?: string;           // destination bank
	n2?: string;           // merchant/beneficiary description
	at3: number;           // transaction amount
	tp?: number;           // purpose code (default 0)
	at7?: number;          // fee (default 0)
	service?: number;      // service code (default 0)
	service_name?: string; // service category (default "Y")
	z1: string;            // transaction timestamp (ISO 8601)
	h1?: string;           // device model
	is_financial?: number; // 1=financial, 0=non-financial
	status?: string;       // "SUCCESS" default
	channel?: string;      // "Livin" default
	lat?: number | null;
	lon?: number | null;
}

// ---- V2 Timing ----

export interface TimingBreakdown {
	// Individual DB ops
	db_customer_fetch_ms: number;
	db_customer_update_ms: number;
	db_transaction_insert_ms: number;
	db_overflow_check_ms: number;
	db_txn_lookups_ms?: number;  // Only present when LOOKUP_MODE=db
	// CPU
	rules_eval_ms: number;
	// Phase aggregates
	db_read_ms: number;
	db_write_ms: number;
	app_processing_ms: number;
	// Totals
	total_db_ms: number;
	total_ms: number;
}

// ---- V2 Response ----

export interface FraudScore {
	final_score: number;       // 0-100
	risk_level: RiskLevel;
	rule_scores: Record<string, number>;  // sparse: only triggered rules
	triggered_count: number;
}

export interface RuleAnalysis {
	rule: string;              // "var_1" through "var_31"
	name: string;              // human-readable name
	category: string;          // "blacklist", "device", "velocity", "amount", "behavioral", "pattern"
	triggered: boolean;
	score: number;
	details: Record<string, unknown>;
}

export interface ScoreTransactionResponse {
	transaction_id: string;
	customer_id: string;
	fraud_score: FraudScore;
	analysis: RuleAnalysis[];
	app_processing_ms: number;
	total_time_ms: number;
	timing: TimingBreakdown;
	recorded_at: string;
}

// ---- Config Mode Types ----

export type UpdateMode = 'standard' | 'pipeline' | 'aggregation';
export type InsertMode = 'sync' | 'none';

export interface UpdateModeResponse {
	update_mode: UpdateMode;
	at6_computed_by: string;
}

export interface LookupModeResponse {
	lookup_mode: 'memory' | 'db';
	db_ops_per_txn: number;
}

export interface InsertModeResponse {
	insert_mode: InsertMode;
	description: string;
}

export type InsertMode = 'sync' | 'none';

export interface InsertModeResponse {
	insert_mode: InsertMode;
	description: string;
}

// ---- Mock Data Types (kept for load test compatibility) ----

export interface MockCustomer {
	customer_id: string;
	name: string;
	account_ids: string[];
	province: string;
}

export interface MockTransaction {
	customer_id: string;
	account_id: string;
	amount: number;
	channel: Channel;
	timestamp: string;
	location: {
		type: string;
		coordinates: [number, number];
	};
	city: string;
	province: string;
	merchant: {
		id: string;
		name: string;
		mcc: string;
		category: string;
	};
	device: {
		device_id: string;
		device_type: string;
		ip: string;
	};
	fraud_metadata?: {
		injected_type: string;
		expected_rules: string[];
	} | null;
}

export type FraudType = 'velocity' | 'impossible_travel' | 'blacklist' | 'ato' | 'card_testing' | 'midnight_burst' | null;

export interface ErrorResponse {
	error: string;
	message: string;
}

export interface HealthResponse {
	status: 'healthy' | 'unhealthy';
	database: 'connected' | 'disconnected';
	sharding: {
		enabled: boolean;
		shards: number;
	};
	collections: Record<string, { exists: boolean; sharded: boolean }>;
	indexes: 'verified' | 'missing';
}
