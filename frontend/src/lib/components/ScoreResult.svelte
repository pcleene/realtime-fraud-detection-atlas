<script lang="ts">
	import type { ScoreTransactionResponse } from '$lib/types';
	import RiskBadge from './RiskBadge.svelte';
	import AnalysisBreakdown from './AnalysisBreakdown.svelte';

	export let result: ScoreTransactionResponse;
	export let lookupMode: 'memory' | 'db' = 'memory';

	$: timing = result?.timing;
	$: hasTxnLookups = timing && timing.db_txn_lookups_ms && timing.db_txn_lookups_ms > 0;
	$: insertSkipped = result?.transaction_id === 'score-only';

	let showDetailedTiming = false;
</script>

<div class="card space-y-6">
	<div class="flex items-center justify-between">
		<h2 class="text-xl font-bold text-gray-900">Scoring Result</h2>
		<div class="text-sm text-gray-500 text-right">
			<div>App Processing: <span class="font-semibold text-blue-600">{(result.app_processing_ms ?? 0).toFixed(2)}ms</span></div>
			<div>DB Write: <span class="font-semibold text-purple-600">{(timing?.db_write_ms ?? 0).toFixed(2)}ms</span></div>
			<div>Total: <span class="font-semibold text-gray-700">{(result.total_time_ms ?? 0).toFixed(2)}ms</span></div>
		</div>
	</div>

	<div class="flex justify-center py-4">
		<RiskBadge level={result.fraud_score.risk_level} score={result.fraud_score.final_score} />
	</div>

	<div class="border-t pt-4">
		<div class="grid grid-cols-2 gap-4 text-sm">
			<div>
				<span class="text-gray-500">Transaction ID:</span>
				{#if insertSkipped}
					<span class="ml-2 text-sm text-amber-600 font-medium">score-only (insert_mode=none)</span>
				{:else}
					<span class="ml-2 font-mono text-gray-900">{result.transaction_id}</span>
				{/if}
			</div>
			<div>
				<span class="text-gray-500">Recorded at:</span>
				<span class="ml-2 text-gray-900">{new Date(result.recorded_at).toLocaleString()}</span>
			</div>
			<div>
				<span class="text-gray-500">Rules triggered:</span>
				<span class="ml-2 font-semibold text-gray-900">{result.fraud_score.triggered_count} / {result.analysis.length}</span>
			</div>
		</div>
	</div>

	<!-- Timing Breakdown Section -->
	{#if timing}
	<div class="border-t pt-4">
		<div class="flex items-center justify-between mb-3">
			<h3 class="text-lg font-semibold text-gray-800">Performance Breakdown</h3>
			<button
				class="text-sm text-blue-600 hover:text-blue-800 underline"
				on:click={() => showDetailedTiming = !showDetailedTiming}
			>
				{showDetailedTiming ? 'Hide Details' : 'Show Details'}
			</button>
		</div>

		<!-- 3-Phase Summary Bars -->
		<div class="space-y-3">
			<!-- Phase 1: DB Read -->
			<div class="flex items-center gap-3">
				<span class="w-24 text-sm text-gray-600">DB Read</span>
				<div class="flex-1 bg-gray-200 rounded-full h-5 overflow-hidden">
					<div
						class="bg-amber-500 h-full rounded-full flex items-center justify-end pr-2"
						style="width: {Math.max(4, Math.min(100, (timing.db_read_ms / timing.total_ms) * 100))}%"
					>
						<span class="text-xs text-white font-semibold">{timing.db_read_ms.toFixed(1)}ms</span>
					</div>
				</div>
				<span class="w-16 text-right text-xs font-mono text-amber-600">
					{timing.db_read_ms.toFixed(1)}ms
				</span>
			</div>

			<!-- Phase 2: Rules -->
			<div class="flex items-center gap-3">
				<span class="w-24 text-sm text-gray-600">Rules</span>
				<div class="flex-1 bg-gray-200 rounded-full h-5 overflow-hidden">
					<div
						class="bg-green-500 h-full rounded-full flex items-center justify-end pr-2"
						style="width: {Math.max(4, Math.min(100, (timing.rules_eval_ms / timing.total_ms) * 100))}%"
					>
						<span class="text-xs text-white font-semibold">{timing.rules_eval_ms.toFixed(1)}ms</span>
					</div>
				</div>
				<span class="w-16 text-right text-xs font-mono text-green-600">
					{timing.rules_eval_ms.toFixed(1)}ms
				</span>
			</div>

			<!-- Phase 3: DB Write -->
			<div class="flex items-center gap-3">
				<span class="w-24 text-sm text-gray-600">DB Write</span>
				<div class="flex-1 bg-gray-200 rounded-full h-5 overflow-hidden">
					<div
						class="bg-purple-500 h-full rounded-full flex items-center justify-end pr-2"
						style="width: {Math.max(4, Math.min(100, (timing.db_write_ms / timing.total_ms) * 100))}%"
					>
						<span class="text-xs text-white font-semibold">{timing.db_write_ms.toFixed(1)}ms</span>
					</div>
				</div>
				<span class="w-16 text-right text-xs font-mono text-purple-600">
					{timing.db_write_ms.toFixed(1)}ms
				</span>
			</div>
		</div>

		<!-- Detailed Breakdown (collapsible) -->
		{#if showDetailedTiming}
		<div class="mt-4 bg-gray-50 rounded-lg p-4 text-sm">
			<div class="grid grid-cols-2 gap-x-8 gap-y-2">
				<!-- Phase 1 -->
				<div class="col-span-2 font-semibold text-amber-700 border-b pb-1 mb-1">Phase 1 — DB Read</div>
				<div class="flex justify-between">
					<span class="text-gray-600">Customer fetch:</span>
					<span class="font-mono text-amber-600">{timing.db_customer_fetch_ms.toFixed(2)}ms</span>
				</div>
				{#if hasTxnLookups}
				<div class="flex justify-between">
					<span class="text-gray-600">Txn lookups (DB mode):</span>
					<span class="font-mono text-amber-600">{(timing.db_txn_lookups_ms ?? 0).toFixed(2)}ms</span>
				</div>
				{/if}
				{#if timing.db_overflow_check_ms > 0}
				<div class="flex justify-between">
					<span class="text-gray-600">Overflow check:</span>
					<span class="font-mono text-amber-600">{timing.db_overflow_check_ms.toFixed(2)}ms</span>
				</div>
				{/if}
				<div class="col-span-2 flex justify-between text-xs text-amber-700 font-semibold mt-1 pt-1 border-t border-dashed">
					<span>Phase 1 total:</span>
					<span class="font-mono">{timing.db_read_ms.toFixed(2)}ms</span>
				</div>

				<!-- Phase 2 -->
				<div class="col-span-2 font-semibold text-green-700 border-b pb-1 mb-1 mt-3">Phase 2 — Rules (CPU)</div>
				<div class="flex justify-between">
					<span class="text-gray-600">31 rules evaluation:</span>
					<span class="font-mono text-green-600">{timing.rules_eval_ms.toFixed(2)}ms</span>
				</div>

				<!-- Phase 3 -->
				<div class="col-span-2 flex items-center justify-between font-semibold text-purple-700 border-b pb-1 mb-1 mt-3">
					<span>Phase 3 — DB Write</span>
					{#if insertSkipped}
						<span class="text-xs font-normal bg-amber-100 text-amber-700 px-2 py-0.5 rounded">insert skipped</span>
					{:else}
						<span class="text-xs font-normal bg-purple-100 px-2 py-0.5 rounded">parallel</span>
					{/if}
				</div>
				<div class="flex justify-between">
					<span class="text-gray-600">Customer update:</span>
					<span class="font-mono text-purple-600">{timing.db_customer_update_ms.toFixed(2)}ms</span>
				</div>
				{#if insertSkipped}
				<div class="flex justify-between">
					<span class="text-gray-400">Transaction insert:</span>
					<span class="font-mono text-amber-600">skipped</span>
				</div>
				{:else}
				<div class="flex justify-between">
					<span class="text-gray-600">Transaction insert:</span>
					<span class="font-mono text-purple-600">{timing.db_transaction_insert_ms.toFixed(2)}ms</span>
				</div>
				{/if}
				<div class="col-span-2 flex justify-between text-xs text-purple-700 font-semibold mt-1 pt-1 border-t border-dashed">
					<span>Wall-clock (parallel):</span>
					<span class="font-mono">{timing.db_write_ms.toFixed(2)}ms</span>
				</div>

				<!-- Totals -->
				<div class="col-span-2 font-semibold text-gray-700 border-b pb-1 mb-1 mt-3">Totals</div>
				<div class="flex justify-between">
					<span class="text-gray-600">App processing (Phase 1+2):</span>
					<span class="font-mono text-blue-600 font-semibold">{timing.app_processing_ms.toFixed(2)}ms</span>
				</div>
				<div class="flex justify-between">
					<span class="text-gray-600">Total DB time (sum):</span>
					<span class="font-mono text-gray-600">{timing.total_db_ms.toFixed(2)}ms</span>
				</div>
				<div class="col-span-2 flex justify-between text-sm font-bold text-gray-900 mt-1 pt-1 border-t">
					<span>End-to-end:</span>
					<span class="font-mono">{timing.total_ms.toFixed(2)}ms</span>
				</div>
			</div>
		</div>
		{/if}
	</div>
	{/if}

	<div class="border-t pt-4">
		<AnalysisBreakdown analysis={result.analysis} triggeredCount={result.fraud_score.triggered_count} />
	</div>
</div>
