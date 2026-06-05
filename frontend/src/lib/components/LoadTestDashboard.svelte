<script lang="ts">
	import {
		getLoadTestProgress,
		getLoadTestResult,
		startLocustTest,
		stopLocustTest,
		getLocustStats,
		resetLocustStats,
		type LoadTestProgress,
		type LoadTestResult,
		type LocustStats,
		type LocustTarget
	} from '$lib/api';
	import RiskBadge from './RiskBadge.svelte';
	import type { RiskLevel, InsertMode } from '$lib/types';

	// Insert mode prop from parent (reflects current engine config)
	export let insertMode: InsertMode = 'sync';

	// Run mode: always bastion for production AWS testing
	let runMode: LocustTarget = 'bastion';

	// Test configuration
	let targetTps = 10000;
	let durationSeconds = 30;
	let concurrency = 100;

	// Test state - export isRunning for parent binding
	export let isRunning = false;
	let currentTestId: string | null = null;
	let progress: LoadTestProgress | null = null;
	let locustStats: LocustStats | null = null;  // For bastion/Locust mode
	let result: LoadTestResult | null = null;
	let error: string | null = null;
	let pollInterval: ReturnType<typeof setInterval> | null = null;
	let testStartTime: Date | null = null;  // Track when Locust test started
	let settleCountdown = 0;  // Settle delay countdown (seconds remaining)
	let peakTps = 0;  // Highest TPS observed during this test

	// Live transaction feed from backend
	let recentTransactions: Array<{
		id: string;
		customerId: string;
		amount: number;
		channel: string;
		riskLevel: RiskLevel;
		latencyMs: number;
		scoringMs: number;  // Time for reads + rule evaluation
		persistMs: number;  // Time for writes
		timestamp: Date;
	}> = [];

	// Channel label mapping
	const channelLabels: Record<string, string> = {
		mobile_banking: 'Mobile',
		internet_banking: 'Web',
		atm: 'ATM',
		edc: 'EDC',
		qris: 'QRIS'
	};
	
	function formatAmount(amount: number): string {
		if (amount >= 1000000) return `${(amount / 1000000).toFixed(1)}M`;
		if (amount >= 1000) return `${(amount / 1000).toFixed(0)}K`;
		return amount.toString();
	}

	// TPS presets
	const tpsPresets = [
		{ label: '2.5K', value: 2500 },
		{ label: '5K', value: 5000 },
		{ label: '10K', value: 10000 },
		{ label: '25K', value: 25000 },
		{ label: '50K', value: 50000 }
	];

	// Duration presets
	const durationPresets = [
		{ label: '10s', value: 10 },
		{ label: '30s', value: 30 },
		{ label: '60s', value: 60 },
		{ label: '120s', value: 120 }
	];

	// Helper: wait ms with a visible countdown
	function settleDelay(totalSeconds: number): Promise<void> {
		return new Promise((resolve) => {
			settleCountdown = totalSeconds;
			const interval = setInterval(() => {
				settleCountdown -= 1;
				if (settleCountdown <= 0) {
					clearInterval(interval);
					settleCountdown = 0;
					resolve();
				}
			}, 1000);
		});
	}

	// Export methods for parent component to call
	export async function startTest() {
		error = null;
		result = null;
		recentTransactions = [];
		locustStats = null;
		peakTps = 0;
		isRunning = true;

		try {
			// 1. Reset stats for a clean slate
			await resetLocustStats(runMode);

			// 2. Wait for mode propagation across all workers (2s TTL cache)
			await settleDelay(4);

			// 3. Reset again to catch any stale data logged during settle
			await resetLocustStats(runMode);

			// 4. Start the Locust swarm
			// Map targetTps to user_count (Locust uses users, not TPS directly)
			// Original formula that achieved 6.4k TPS at 28ms avg latency
			const userCount = Math.max(Math.ceil(targetTps / 50), 10);  // 10K -> 200 users
			const spawnRate = Math.min(Math.ceil(userCount / 5), 200);  // Spawn over ~5 seconds

			const startResult = await startLocustTest({
				user_count: userCount,
				spawn_rate: spawnRate,
				target: runMode
			});

			testStartTime = new Date();
			// Use the real test_id from the backend (stored in MongoDB)
			currentTestId = startResult.test_id;

			// 5. Start polling both Locust stats AND progress for transaction feed
			pollInterval = setInterval(pollLocustStats, 500);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to start test';
			isRunning = false;
		}
	}

	async function pollLocustStats() {
		if (!testStartTime) return;

		try {
			// Poll Locust stats for RPS and latency percentiles
			const stats = await getLocustStats(runMode);
			locustStats = stats;
			if (stats.current_rps > peakTps) peakTps = stats.current_rps;

			// Also poll progress endpoint for transaction feed and risk distribution
			// This uses the sampled data from /score-transaction endpoint
			if (currentTestId) {
				try {
					const newProgress = await getLoadTestProgress(currentTestId);

					// Get transaction feed from sampled data
					if (newProgress.recent_transactions && newProgress.recent_transactions.length > 0) {
						recentTransactions = newProgress.recent_transactions.map((txn) => ({
							id: `${txn.customer_id}-${txn.timestamp}`,
							customerId: txn.customer_id,
							amount: txn.amount,
							channel: txn.channel,
							riskLevel: txn.risk_level as RiskLevel,
							latencyMs: txn.latency_ms,
							scoringMs: txn.scoring_ms || 0,
							persistMs: txn.persist_ms || 0,
							timestamp: new Date(txn.timestamp)
						})).reverse();  // Most recent first
					}

					// Use progress for risk distribution (sampled from actual transactions)
					progress = newProgress;
				} catch {
					// Ignore progress polling errors - Locust stats are primary
				}
			}

			// Check if we've exceeded the duration
			const elapsed = (Date.now() - testStartTime.getTime()) / 1000;
			if (elapsed >= durationSeconds) {
				// Stop the test
				await stopLocustTest(runMode);
				stopPolling();
				isRunning = false;
			}
		} catch (e) {
			// Ignore polling errors
		}
	}

	function stopPolling() {
		if (pollInterval) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
	}

	export async function stopTest() {
		try {
			await stopLocustTest(runMode);
		} catch (e) {
			// Ignore
		}
		stopPolling();
		isRunning = false;
	}

	function formatNumber(n: number): string {
		if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
		if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
		return n.toFixed(0);
	}

	function getLatencyColor(ms: number): string {
		if (ms < 50) return 'text-green-600';
		if (ms < 100) return 'text-yellow-600';
		return 'text-red-600';
	}

	function getLatencyBgColor(ms: number): string {
		if (ms < 50) return 'bg-green-500';
		if (ms < 100) return 'bg-yellow-500';
		return 'bg-red-500';
	}

	function getTpsColor(tps: number, target: number): string {
		const ratio = tps / target;
		if (ratio >= 0.9) return 'text-green-600';
		if (ratio >= 0.7) return 'text-yellow-600';
		return 'text-red-600';
	}

	// Reactive stats - use Locust stats for TPS/latency, progress for risk distribution
	$: lowRiskCount = progress?.risk_distribution?.low || 0;
	$: mediumRiskCount = progress?.risk_distribution?.medium || 0;
	$: highRiskCount = progress?.risk_distribution?.high || 0;
	$: totalCount = locustStats?.total_requests || 0;
	$: currentTps = locustStats?.current_rps || 0;
	$: elapsedSeconds = testStartTime ? (Date.now() - testStartTime.getTime()) / 1000 : 0;

	// Latency breakdown: Locust (end-to-end) vs App (MongoDB + processing)
	// Locust measures: bastion → EC2 → processing → EC2 → bastion (includes network)
	// App measures: just the processing inside EC2 (MongoDB queries + rule scoring)
	$: locustAvgLatency = locustStats?.avg_response_time || 0;
	$: locustP50Latency = locustStats?.p50_response_time || 0;
	$: locustP95Latency = locustStats?.p95_response_time || 0;
	$: locustP99Latency = locustStats?.p99_response_time || 0;
	$: rawAppAvg = progress?.avg_latency_ms || 0;
	$: rawAppP95 = progress?.p95_latency_ms || 0;
	$: rawAppP99 = progress?.p99_latency_ms || 0;
	// Use app latency if sampler is feeding data, otherwise fall back to Locust stats
	$: hasAppLatency = rawAppAvg > 0;
	$: appAvgLatency = hasAppLatency ? rawAppAvg : locustAvgLatency;
	$: appP95Latency = hasAppLatency ? rawAppP95 : locustP95Latency;
	$: appP99Latency = hasAppLatency ? rawAppP99 : locustP99Latency;
	$: networkOverhead = hasAppLatency && locustAvgLatency > 0 ? locustAvgLatency - rawAppAvg : 0;
	// Label changes based on data source
	$: latencySource = hasAppLatency ? 'App → MongoDB' : 'End-to-End (Locust)';

	// Scoring vs persist breakdown (from sampled transactions)
	// Scoring = parallel reads + rule evaluation (before writes)
	// Persist = customer update + transaction insert (writes)
	$: avgScoringMs = progress?.avg_scoring_ms || 0;
	$: avgPersistMs = progress?.avg_persist_ms || 0;

	// Cleanup on unmount
	import { onDestroy } from 'svelte';
	onDestroy(() => {
		stopPolling();
	});
</script>

<div class="space-y-4">
	<!-- Infrastructure Overview (compact) -->
	<div class="card bg-gradient-to-r from-slate-50 to-blue-50/30 border border-slate-200 py-2">
		<div class="text-xs font-medium text-gray-600 mb-2">Infrastructure</div>
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-2 text-[11px]">
				<div class="flex items-center gap-1.5 px-2 py-1 rounded bg-amber-50 border border-amber-200">
					<span class="font-semibold text-amber-700">Bastion</span>
					<span class="text-amber-500">Locust 95w</span>
				</div>
				<span class="text-gray-300">→</span>
				<div class="flex items-center gap-1.5 px-2 py-1 rounded bg-orange-50 border border-orange-200">
					<span class="font-semibold text-orange-700">ALB</span>
				</div>
				<span class="text-gray-300">→</span>
				<div class="flex items-center gap-1.5 px-2 py-1 rounded bg-blue-50 border border-blue-200">
					<span class="font-semibold text-blue-700">8×EC2</span>
					<span class="text-blue-500">c6i.16xl</span>
				</div>
				<span class="text-gray-400 text-[9px] px-1">PrivateLink</span>
				<div class="flex items-center gap-1.5 px-2 py-1 rounded bg-green-50 border border-green-200">
					<span class="font-semibold text-green-700">Atlas M140</span>
					<span class="text-green-500">6 shards</span>
				</div>
			</div>
			<div class="flex items-center gap-2 text-[10px] text-gray-400">
				<span>40M customers</span>
				<span>·</span>
				<span>ap-southeast-1</span>
				<span class="px-1.5 py-0.5 rounded bg-green-100 text-green-700 font-medium">LIVE</span>
			</div>
		</div>
	</div>

	<!-- Configuration Cards Row -->
	<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
		<!-- Target TPS Card -->
		<div class="card">
			<label class="block text-sm font-medium text-gray-700 mb-3">Target TPS</label>
			<div class="flex gap-1.5">
				{#each tpsPresets as preset}
					<button
						on:click={() => (targetTps = preset.value)}
						class="flex-1 px-2 py-2.5 text-sm font-medium rounded-lg transition-all {targetTps === preset.value
							? 'bg-RegionalBank-blue text-white shadow-sm'
							: 'bg-gray-100 hover:bg-gray-200 text-gray-700'}"
						disabled={isRunning}
					>
						{preset.label}
					</button>
				{/each}
			</div>
		</div>

		<!-- Duration Card -->
		<div class="card">
			<label class="block text-sm font-medium text-gray-700 mb-3">Duration</label>
			<div class="flex gap-1.5">
				{#each durationPresets as preset}
					<button
						on:click={() => (durationSeconds = preset.value)}
						class="flex-1 px-2 py-2.5 text-sm font-medium rounded-lg transition-all {durationSeconds === preset.value
							? 'bg-RegionalBank-blue text-white shadow-sm'
							: 'bg-gray-100 hover:bg-gray-200 text-gray-700'}"
						disabled={isRunning}
					>
						{preset.label}
					</button>
				{/each}
			</div>
		</div>

	</div>

	<!-- Error Display -->
	{#if error}
		<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
			{error}
		</div>
	{/if}

	<!-- Settle Delay Countdown -->
	{#if settleCountdown > 0}
		<div class="bg-amber-50 border border-amber-200 rounded-lg p-4 flex items-center gap-3">
			<div class="w-5 h-5 border-2 border-amber-500 border-t-transparent rounded-full animate-spin"></div>
			<span class="text-amber-700 font-medium">Waiting for mode propagation... {settleCountdown}s</span>
			<span class="text-amber-500 text-sm">(456 workers, 2s TTL cache)</span>
		</div>
	{/if}

	<!-- Stats Dashboard -->
	<div class="card bg-gradient-to-br from-blue-50 to-cyan-50 p-3">
		<div class="flex items-center gap-2 mb-2">
			<span class="text-sm text-blue-600 font-semibold">{latencySource}</span>
			{#if hasAppLatency}
				<span class="text-[10px] text-blue-400 bg-blue-100 px-1.5 py-0.5 rounded">Direct — no bastion hop</span>
			{:else}
				<span class="text-[10px] text-amber-500 bg-amber-100 px-1.5 py-0.5 rounded">Includes network hop</span>
			{/if}
		</div>
		<!-- TPS + Latency Percentiles -->
		<div class="grid grid-cols-7 gap-3 text-center mb-2">
			<div>
				<div class="text-[10px] text-gray-500 uppercase">TPS</div>
				<div class="text-lg font-bold {getTpsColor(currentTps, targetTps)}">{formatNumber(currentTps)}</div>
			</div>
			<div>
				<div class="text-[10px] text-gray-500 uppercase">Requests</div>
				<div class="text-lg font-bold text-blue-700">{formatNumber(locustStats?.total_requests || 0)}</div>
			</div>
			<div>
				<div class="text-[10px] text-gray-500 uppercase">Fail</div>
				<div class="text-lg font-bold {(locustStats?.current_fail_rate || 0) > 1 ? 'text-red-600' : 'text-green-600'}">{(locustStats?.current_fail_rate || 0).toFixed(1)}%</div>
			</div>
			<div class="border-l border-blue-200 pl-3">
				<div class="text-[10px] text-gray-500 uppercase">Avg</div>
				<div class="text-lg font-bold {getLatencyColor(appAvgLatency)}">{appAvgLatency.toFixed(0)}<span class="text-xs">ms</span></div>
			</div>
			<div>
				<div class="text-[10px] text-gray-500 uppercase">P95</div>
				<div class="text-lg font-bold {getLatencyColor(appP95Latency)}">{appP95Latency.toFixed(0)}<span class="text-xs">ms</span></div>
			</div>
			<div>
				<div class="text-[10px] text-gray-500 uppercase">P99</div>
				<div class="text-lg font-bold {getLatencyColor(appP99Latency)}">{appP99Latency.toFixed(0)}<span class="text-xs">ms</span></div>
			</div>
			<div>
				<div class="text-[10px] text-gray-500 uppercase">{hasAppLatency ? 'Network' : 'P50'}</div>
				{#if hasAppLatency}
					<div class="text-lg font-bold text-gray-500">{networkOverhead > 0 ? `~${networkOverhead.toFixed(0)}` : '-'}<span class="text-xs">ms</span></div>
				{:else}
					<div class="text-lg font-bold {getLatencyColor(locustP50Latency)}">{locustP50Latency.toFixed(0)}<span class="text-xs">ms</span></div>
				{/if}
			</div>
		</div>
		<!-- Dynamic breakdown based on insert mode -->
		<div class="mt-2 pt-2 border-t border-blue-200 text-xs">
			{#if insertMode === 'none'}
				<!-- Score-only mode (insert=none): no persist, no bar -->
				<div class="text-center py-1">
					<div class="text-sm font-semibold text-blue-700">Risk Scoring + Feature Update</div>
					<div class="text-sm text-gray-500 mt-2 leading-relaxed">Insert mode: <span class="font-medium text-gray-600">None</span> — MongoDB replaces Redis for real-time scoring. Reads customer profile, evaluates 31 rules, updates risk variables. Transaction records persisted to Oracle.</div>
				</div>
			{:else}
				<!-- Sync mode: scoring + persist breakdown -->
				<div class="grid grid-cols-2 gap-2 mb-1.5">
					<div class="flex items-center gap-2">
						<span class="text-gray-500">Score:</span>
						<div class="flex-1 h-2.5 bg-gray-200 rounded overflow-hidden">
							<div class="h-full bg-blue-500 transition-all" style="width: {Math.min(appAvgLatency > 0 ? (avgScoringMs / appAvgLatency) * 100 : 0, 100)}%"></div>
						</div>
						<span class="font-bold {getLatencyColor(avgScoringMs)}">{avgScoringMs.toFixed(0)}ms <span class="font-normal text-gray-400">({appAvgLatency > 0 ? ((avgScoringMs / appAvgLatency) * 100).toFixed(0) : 0}%)</span></span>
					</div>
					<div class="flex items-center gap-2">
						<span class="text-gray-500">Persist:</span>
						<div class="flex-1 h-2.5 bg-gray-200 rounded overflow-hidden">
							<div class="h-full bg-green-500 transition-all" style="width: {Math.min(appAvgLatency > 0 ? (avgPersistMs / appAvgLatency) * 100 : 0, 100)}%"></div>
						</div>
						<span class="font-bold {getLatencyColor(avgPersistMs)}">{avgPersistMs.toFixed(0)}ms <span class="font-normal text-gray-400">({appAvgLatency > 0 ? ((avgPersistMs / appAvgLatency) * 100).toFixed(0) : 0}%)</span></span>
					</div>
				</div>
				<div class="text-sm text-gray-500 mt-1 text-center leading-relaxed">
					Insert mode: <span class="font-medium text-gray-600">Sync</span> — MongoDB replaces both Redis and Oracle. Score = read profile + evaluate rules + update features. Persist = write scored transaction record to MongoDB.
				</div>
			{/if}
		</div>
	</div>

	<!-- Risk Distribution Row -->
	<div class="space-y-2">
		<div class="flex items-center gap-2">
			<span class="text-xs font-medium text-gray-600">Risk Distribution</span>
			<span class="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded" title="1-in-100 transactions are sampled for risk distribution stats">1% sample</span>
		</div>
		<div class="grid grid-cols-4 gap-3">
			<div class="card bg-green-50 p-3">
				<div class="text-xs text-green-600 font-medium">Low Risk</div>
				<div class="text-xl font-bold text-green-700">{formatNumber(lowRiskCount)}</div>
			</div>
			<div class="card bg-yellow-50 p-3">
				<div class="text-xs text-yellow-600 font-medium">Medium Risk</div>
				<div class="text-xl font-bold text-yellow-700">{formatNumber(mediumRiskCount)}</div>
			</div>
			<div class="card bg-red-50 p-3">
				<div class="text-xs text-red-600 font-medium">High Risk</div>
				<div class="text-xl font-bold text-red-700">{formatNumber(highRiskCount)}</div>
			</div>
			<div class="card bg-RegionalBank-light p-3">
				<div class="text-xs text-RegionalBank-blue font-medium">Sampled</div>
				<div class="text-xl font-bold text-RegionalBank-blue">{formatNumber(lowRiskCount + mediumRiskCount + highRiskCount)}</div>
			</div>
		</div>
	</div>

	<!-- Latency Timeline Chart -->
	{#if recentTransactions.length > 0 || result}
		<div class="card">
			<h3 class="text-sm font-semibold text-gray-700 mb-3">
				{result ? 'Final Latency Distribution' : 'Live Latency Timeline'}
			</h3>

			{#if result && result.latency_histogram}
				<!-- Histogram for final results -->
				<div class="flex items-end gap-1 h-32 bg-gray-50 rounded-lg p-2">
					{#each result.latency_histogram as bucket}
						{@const height = Math.min(Math.max(bucket.percentage * 2.5, 2), 100)}
						<div
							class="flex-1 bg-RegionalBank-blue hover:bg-RegionalBank-gold rounded-t transition-colors cursor-pointer"
							style="height: {height}%"
							title="{bucket.bucket_ms}: {bucket.count} ({bucket.percentage.toFixed(1)}%)"
						></div>
					{/each}
				</div>
				<div class="flex justify-between text-xs text-gray-400 mt-1">
					<span>{result.min_latency_ms.toFixed(0)}ms</span>
					<span>P50: {result.p50_latency_ms.toFixed(0)}ms | P95: {result.p95_latency_ms.toFixed(0)}ms | P99: {result.p99_latency_ms.toFixed(0)}ms</span>
					<span>{result.max_latency_ms.toFixed(0)}ms</span>
				</div>
			{:else}
				<!-- Live timeline -->
				<div class="flex items-end gap-0.5 h-24">
					{#each recentTransactions.slice(0, 100) as txn, i}
						{@const height = Math.min(Math.max((txn.latencyMs / 200) * 100, 5), 100)}
						<div
							class="flex-1 rounded-t transition-all {getLatencyBgColor(txn.latencyMs)}"
							style="height: {height}%"
							title="{txn.latencyMs.toFixed(1)}ms - {txn.riskLevel}"
						></div>
					{/each}
				</div>
				<div class="flex justify-between text-xs text-gray-500 mt-2">
					<div class="flex items-center gap-4">
						<span class="flex items-center gap-1">
							<span class="w-3 h-3 bg-green-500 rounded-sm"></span> &lt;50ms
						</span>
						<span class="flex items-center gap-1">
							<span class="w-3 h-3 bg-yellow-500 rounded-sm"></span> 50-100ms
						</span>
						<span class="flex items-center gap-1">
							<span class="w-3 h-3 bg-red-500 rounded-sm"></span> &gt;100ms
						</span>
					</div>
					<span>Target: &lt;50ms</span>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Transaction Feed -->
	<div class="card">
		<div class="flex items-center justify-between mb-3">
			<div class="flex items-center gap-2">
				<h3 class="text-sm font-semibold text-gray-700">Transaction Feed</h3>
				<span class="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded" title="Latency shown is App processing time (MongoDB + scoring), not Locust round-trip">{hasAppLatency ? 'App Latency' : 'Locust Latency'}</span>
			</div>
			{#if isRunning}
				<div class="flex items-center gap-2">
					<div class="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
					<span class="text-xs text-gray-500">Live</span>
				</div>
			{/if}
		</div>

		{#if recentTransactions.length === 0 && !isRunning}
			<div class="text-center text-gray-400 py-8">
				Click "Start Load Test" to begin generating transactions at scale.
			</div>
		{:else}
			<div class="space-y-2 max-h-[500px] overflow-y-auto">
				{#each recentTransactions as txn (txn.id)}
					<div class="flex items-center gap-4 p-3 rounded-xl bg-gray-50 hover:bg-gray-100 transition-colors">
						<div class="flex-shrink-0 w-24">
							<RiskBadge level={txn.riskLevel} score={txn.riskLevel === 'high' ? 75 : txn.riskLevel === 'medium' ? 50 : 20} small />
						</div>
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-3">
								<span class="font-semibold text-gray-900 font-mono text-sm">{txn.customerId}</span>
								<span class="px-2 py-1 bg-gray-200 rounded-md text-xs font-medium text-gray-700">{channelLabels[txn.channel] || txn.channel}</span>
							</div>
							<div class="text-sm text-gray-500 mt-1 flex items-center gap-3">
								<span class="font-medium text-gray-700">Rp {formatAmount(txn.amount)}</span>
								<span class="text-gray-300">•</span>
								<span>{txn.timestamp.toLocaleTimeString()}</span>
							</div>
						</div>
						<!-- App latency (MongoDB + scoring, no network) -->
						<div class="flex-shrink-0 flex items-center gap-2">
							<div class="{getLatencyColor(txn.latencyMs)} font-bold text-xl tabular-nums">{txn.latencyMs.toFixed(0)}<span class="text-xs font-normal ml-0.5">ms</span></div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Final Results Summary -->
	{#if result}
		<div class="card bg-gradient-to-r from-green-50 to-blue-50">
			<div class="flex items-center justify-between mb-4">
				<h3 class="text-lg font-semibold text-gray-900">Test Complete: {result.test_id}</h3>
				<span class="px-3 py-1 rounded-full text-sm font-medium bg-green-100 text-green-800">
					{result.status}
				</span>
			</div>

			<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
				<div class="bg-white rounded-xl p-4 shadow-sm">
					<div class="text-xs text-gray-500 uppercase tracking-wide">Throughput</div>
					<div class="text-2xl font-bold text-blue-600">{result.throughput_tps.toFixed(0)} TPS</div>
					<div class="text-xs text-gray-400">{((result.throughput_tps / targetTps) * 100).toFixed(0)}% of target</div>
				</div>
				<div class="bg-white rounded-xl p-4 shadow-sm">
					<div class="text-xs text-gray-500 uppercase tracking-wide">Success Rate</div>
					<div class="text-2xl font-bold text-green-600">
						{((result.successful / result.total_transactions) * 100).toFixed(1)}%
					</div>
					<div class="text-xs text-gray-400">{formatNumber(result.successful)} / {formatNumber(result.total_transactions)}</div>
				</div>
				<div class="bg-white rounded-xl p-4 shadow-sm">
					<div class="text-xs text-gray-500 uppercase tracking-wide">Avg Latency</div>
					<div class="text-2xl font-bold {getLatencyColor(result.avg_latency_ms)}">{result.avg_latency_ms.toFixed(1)}ms</div>
					<div class="text-xs text-gray-400">P99: {result.p99_latency_ms.toFixed(1)}ms</div>
				</div>
				<div class="bg-white rounded-xl p-4 shadow-sm">
					<div class="text-xs text-gray-500 uppercase tracking-wide">Duration</div>
					<div class="text-2xl font-bold text-gray-700">{result.duration_seconds.toFixed(1)}s</div>
					<div class="text-xs text-gray-400">{formatNumber(result.total_transactions)} total txns</div>
				</div>
			</div>

			<div class="mt-4 text-center">
				<button
					on:click={() => { result = null; recentTransactions = []; }}
					class="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 hover:bg-white/50 rounded-lg transition-colors"
				>
					Clear Results
				</button>
			</div>
		</div>
	{/if}

	<!-- Performance Targets Reference -->
	<div class="card bg-gray-50 text-sm">
		<div class="flex items-center justify-between">
			<div>
				<span class="font-medium text-gray-700">RegionalBank Target:</span>
				<span class="text-gray-600 ml-2">5,000-10,000 TPS @ &lt;50ms P99</span>
			</div>
			<div class="text-xs text-gray-400">
				Note: Actual throughput depends on MongoDB cluster capacity & network latency
			</div>
		</div>
	</div>
</div>
