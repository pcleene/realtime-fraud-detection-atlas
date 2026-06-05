<script lang="ts">
	import type { ScoreTransactionResponse, FraudType } from '$lib/types';
	import { getMockCustomer, getMockTransaction, scoreTransaction } from '$lib/api';
	import RiskBadge from './RiskBadge.svelte';

	interface TransactionRecord {
		id: string;
		result: ScoreTransactionResponse;
		customerName: string;
		amount: number;
		channel: string;
		fraudInjected: string | null;
	}

	let transactions: TransactionRecord[] = [];
	let isStreaming = false;
	let streamInterval: ReturnType<typeof setInterval> | null = null;
	let selectedFraudType: FraudType = null;
	let transactionsPerSecond = 2;

	const fraudTypes: { value: FraudType; label: string }[] = [
		{ value: null, label: 'Random (12% fraud)' },
		{ value: 'velocity', label: 'Velocity Fraud' },
		{ value: 'impossible_travel', label: 'Impossible Travel' },
		{ value: 'blacklist', label: 'Blacklist Proximity' },
		{ value: 'ato', label: 'Account Takeover' },
		{ value: 'card_testing', label: 'Card Testing' },
		{ value: 'midnight_burst', label: 'Midnight Burst' }
	];

	async function generateAndScore() {
		try {
			// Get mock customer and transaction
			const customer = await getMockCustomer();
			const mockTxn = await getMockTransaction(selectedFraudType);

			// Build V2 score request
			const request = {
				customer_id: customer.customer_id,
				b2: customer.account_ids[0],
				at3: mockTxn.amount,
				lat: mockTxn.location.coordinates[1],
				lon: mockTxn.location.coordinates[0],
				z1: mockTxn.timestamp,
				channel: mockTxn.channel,
				n2: mockTxn.merchant.name,
				service: parseInt(mockTxn.merchant.mcc) || 0,
				h1: mockTxn.device.device_id
			};

			// Score the transaction
			const result = await scoreTransaction(request);

			// Add to feed
			const record: TransactionRecord = {
				id: result.transaction_id,
				result,
				customerName: customer.name,
				amount: mockTxn.amount,
				channel: mockTxn.channel,
				fraudInjected: mockTxn.fraud_metadata?.injected_type || null
			};

			transactions = [record, ...transactions].slice(0, 50); // Keep last 50
		} catch (e) {
			console.error('Error generating transaction:', e);
		}
	}

	function startStream() {
		if (isStreaming) return;
		isStreaming = true;
		const intervalMs = 1000 / transactionsPerSecond;
		streamInterval = setInterval(generateAndScore, intervalMs);
	}

	function stopStream() {
		isStreaming = false;
		if (streamInterval) {
			clearInterval(streamInterval);
			streamInterval = null;
		}
	}

	function clearFeed() {
		transactions = [];
	}

	function formatAmount(amount: number): string {
		return new Intl.NumberFormat('id-ID', {
			style: 'currency',
			currency: 'IDR',
			minimumFractionDigits: 0
		}).format(amount);
	}

	// Stats
	$: avgScoringTime =
		transactions.length > 0
			? transactions.reduce((sum, t) => sum + t.result.app_processing_ms, 0) / transactions.length
			: 0;

	$: avgPersistenceTime =
		transactions.length > 0
			? transactions.reduce((sum, t) => sum + (t.result.timing?.db_write_ms ?? 0), 0) / transactions.length
			: 0;

	$: avgTotalTime =
		transactions.length > 0
			? transactions.reduce((sum, t) => sum + t.result.total_time_ms, 0) / transactions.length
			: 0;

	$: highRiskCount = transactions.filter((t) => t.result.fraud_score.risk_level === 'high').length;
	$: mediumRiskCount = transactions.filter((t) => t.result.fraud_score.risk_level === 'medium').length;
	$: lowRiskCount = transactions.filter((t) => t.result.fraud_score.risk_level === 'low').length;
</script>

<div class="space-y-4">
	<!-- Controls -->
	<div class="card">
		<div class="flex flex-wrap items-center gap-4">
			<div class="flex items-center gap-2">
				<label for="fraud-type-select" class="text-sm font-medium text-gray-700">Fraud Type:</label>
				<select
					id="fraud-type-select"
					bind:value={selectedFraudType}
					class="rounded-md border-gray-300 text-sm focus:border-RegionalBank-blue focus:ring-RegionalBank-blue"
					disabled={isStreaming}
				>
					{#each fraudTypes as ft}
						<option value={ft.value}>{ft.label}</option>
					{/each}
				</select>
			</div>

			<div class="flex items-center gap-2">
				<label for="tps-slider" class="text-sm font-medium text-gray-700">TPS:</label>
				<input
					id="tps-slider"
					type="range"
					min="1"
					max="10"
					bind:value={transactionsPerSecond}
					class="w-24"
					disabled={isStreaming}
				/>
				<span class="text-sm text-gray-600 w-6">{transactionsPerSecond}</span>
			</div>

			<div class="flex gap-2 ml-auto">
				{#if !isStreaming}
					<button
						on:click={generateAndScore}
						class="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
					>
						Single
					</button>
					<button
						on:click={startStream}
						class="px-4 py-1.5 text-sm bg-green-600 hover:bg-green-700 text-white rounded-md transition-colors"
					>
						Start Stream
					</button>
				{:else}
					<button
						on:click={stopStream}
						class="px-4 py-1.5 text-sm bg-red-600 hover:bg-red-700 text-white rounded-md transition-colors"
					>
						Stop Stream
					</button>
				{/if}
				<button
					on:click={clearFeed}
					class="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
					disabled={isStreaming}
				>
					Clear
				</button>
			</div>
		</div>
	</div>

	<!-- Stats Dashboard -->
	<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
		<div class="card bg-blue-50 p-3">
			<div class="text-xs text-blue-600 font-medium">Scoring</div>
			<div class="text-xl font-bold text-blue-700">{avgScoringTime.toFixed(1)}ms</div>
		</div>
		<div class="card bg-purple-50 p-3">
			<div class="text-xs text-purple-600 font-medium">Persistence</div>
			<div class="text-xl font-bold text-purple-700">{avgPersistenceTime.toFixed(1)}ms</div>
		</div>
		<div class="card bg-gray-50 p-3">
			<div class="text-xs text-gray-600 font-medium">Total</div>
			<div class="text-xl font-bold text-gray-700">{avgTotalTime.toFixed(1)}ms</div>
		</div>
		<div class="card bg-green-50 p-3">
			<div class="text-xs text-green-600 font-medium">Low Risk</div>
			<div class="text-xl font-bold text-green-700">{lowRiskCount}</div>
		</div>
		<div class="card bg-yellow-50 p-3">
			<div class="text-xs text-yellow-600 font-medium">Medium Risk</div>
			<div class="text-xl font-bold text-yellow-700">{mediumRiskCount}</div>
		</div>
		<div class="card bg-red-50 p-3">
			<div class="text-xs text-red-600 font-medium">High Risk</div>
			<div class="text-xl font-bold text-red-700">{highRiskCount}</div>
		</div>
		<div class="card bg-RegionalBank-light p-3">
			<div class="text-xs text-RegionalBank-blue font-medium">Total</div>
			<div class="text-xl font-bold text-RegionalBank-blue">{transactions.length}</div>
		</div>
	</div>

	<!-- Timing Bar Chart -->
	{#if transactions.length > 0}
		<div class="card">
			<h3 class="text-sm font-semibold text-gray-700 mb-3">Recent Transaction Timings (last 20)</h3>
			<div class="flex items-end gap-1 h-24">
				{#each transactions.slice(0, 20).reverse() as txn, i}
					{@const scoringHeight = (txn.result.app_processing_ms / 50) * 100}
					{@const persistenceHeight = ((txn.result.timing?.db_write_ms ?? 0) / 50) * 100}
					<div class="flex-1 flex flex-col justify-end" title="{txn.result.total_time_ms.toFixed(1)}ms total">
						<div
							class="bg-purple-400 rounded-t-sm"
							style="height: {Math.min(persistenceHeight, 100)}%"
						></div>
						<div
							class="bg-blue-500 rounded-t-sm"
							style="height: {Math.min(scoringHeight, 100)}%"
						></div>
					</div>
				{/each}
			</div>
			<div class="flex justify-between text-xs text-gray-500 mt-2">
				<div class="flex items-center gap-4">
					<span class="flex items-center gap-1">
						<span class="w-3 h-3 bg-blue-500 rounded-sm"></span> Scoring
					</span>
					<span class="flex items-center gap-1">
						<span class="w-3 h-3 bg-purple-400 rounded-sm"></span> Persistence
					</span>
				</div>
				<span>Target: &lt;50ms</span>
			</div>
		</div>
	{/if}

	<!-- Transaction Feed -->
	<div class="card max-h-96 overflow-y-auto">
		<h3 class="text-sm font-semibold text-gray-700 mb-3 sticky top-0 bg-white pb-2">
			Transaction Feed
		</h3>
		{#if transactions.length === 0}
			<div class="text-center text-gray-400 py-8">
				No transactions yet. Click "Single" or "Start Stream" to generate transactions.
			</div>
		{:else}
			<div class="space-y-2">
				{#each transactions as txn (txn.id)}
					<div
						class="flex items-center gap-3 p-2 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors text-sm"
					>
						<div class="flex-shrink-0">
							<RiskBadge level={txn.result.fraud_score.risk_level} score={txn.result.fraud_score.final_score} small />
						</div>
						<div class="flex-1 min-w-0">
							<div class="font-medium text-gray-900 truncate">{txn.customerName}</div>
							<div class="text-xs text-gray-500">
								{txn.channel} &bull; {formatAmount(txn.amount)}
								{#if txn.fraudInjected}
									<span class="text-red-500 font-medium"> &bull; {txn.fraudInjected}</span>
								{/if}
							</div>
						</div>
						<div class="text-right text-xs flex-shrink-0">
							<div class="text-blue-600">{txn.result.app_processing_ms.toFixed(1)}ms</div>
							<div class="text-gray-400">{txn.result.total_time_ms.toFixed(1)}ms total</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
