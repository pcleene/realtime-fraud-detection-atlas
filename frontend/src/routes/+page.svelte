<script lang="ts">
	import type { ScoreTransactionRequest, ScoreTransactionResponse, HealthResponse, InsertMode } from '$lib/types';
	import { scoreTransaction, checkHealth, ApiError, getInsertMode } from '$lib/api';
	import ScoreForm from '$lib/components/ScoreForm.svelte';
	import ScoreResult from '$lib/components/ScoreResult.svelte';
	import LoadTestDashboard from '$lib/components/LoadTestDashboard.svelte';
	import ModeToggle from '$lib/components/ModeToggle.svelte';
	import { onMount } from 'svelte';

	export let params: Record<string, string> = {};

	let result: ScoreTransactionResponse | null = null;
	let error: string | null = null;
	let loading = false;
	let health: HealthResponse | null = null;
	let activeTab: 'loadtest' | 'manual' = 'loadtest';
	let lookupMode: 'memory' | 'db' = 'memory';
	let insertMode: InsertMode = 'sync';

	// Load test control refs
	let loadTestDashboard: LoadTestDashboard;
	let loadTestRunning = false;

	onMount(async () => {
		try {
			const [h, iRes] = await Promise.all([checkHealth(), getInsertMode()]);
			health = h;
			insertMode = iRes.insert_mode;
		} catch (e) {
			console.error('Health check failed:', e);
		}
	});

	async function handleSubmit(event: CustomEvent<ScoreTransactionRequest>) {
		loading = true;
		error = null;
		result = null;

		try {
			result = await scoreTransaction(event.detail);
		} catch (e) {
			if (e instanceof ApiError) {
				error = `${e.error}: ${e.message}`;
			} else if (e instanceof Error) {
				error = e.message;
			} else {
				error = 'An unexpected error occurred';
			}
		} finally {
			loading = false;
		}
	}

	function handleLookupModeChange(event: CustomEvent<'memory' | 'db'>) {
		lookupMode = event.detail;
	}

	function handleInsertModeChange(event: CustomEvent<InsertMode>) {
		insertMode = event.detail;
	}
</script>

<svelte:head>
	<title>RegionalBank Fraud Detection POC</title>
</svelte:head>

<div class="space-y-6">
	<!-- Health Status Banner -->
	{#if health}
		<div class="rounded-lg p-4 {health.status === 'healthy' ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}">
			<div class="flex items-center justify-between">
				<div class="flex items-center gap-2">
					<div class="w-3 h-3 rounded-full {health.status === 'healthy' ? 'bg-green-500' : 'bg-red-500'}"></div>
					<span class="font-medium {health.status === 'healthy' ? 'text-green-800' : 'text-red-800'}">
						System {health.status === 'healthy' ? 'Healthy' : 'Unhealthy'}
					</span>
				</div>
				<div class="flex items-center gap-4 text-sm">
					<span class="text-gray-600">
						Database: <span class="font-medium">{health.database}</span>
					</span>
					{#if health.sharding.enabled}
						<span class="text-gray-600">
							Sharding: <span class="font-medium">{health.sharding.shards} shards</span>
						</span>
					{/if}
					<span class="text-gray-600">
						Indexes: <span class="font-medium">{health.indexes}</span>
					</span>
				</div>
			</div>
		</div>
	{/if}

	<!-- Mode Toggles -->
	<ModeToggle on:lookupModeChange={handleLookupModeChange} on:insertModeChange={handleInsertModeChange} />

	<!-- Tab Navigation with Action Button -->
	<div class="border-b border-gray-200 mb-6">
		<div class="flex items-end justify-between pb-0">
			<nav class="flex gap-4" aria-label="Tabs">
				<button
					on:click={() => (activeTab = 'loadtest')}
					class="py-3 px-1 border-b-2 font-medium text-sm transition-colors {activeTab === 'loadtest'
						? 'border-RegionalBank-blue text-RegionalBank-blue'
						: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
				>
					Load Testing
				</button>
				<button
					on:click={() => (activeTab = 'manual')}
					class="py-3 px-1 border-b-2 font-medium text-sm transition-colors {activeTab === 'manual'
						? 'border-RegionalBank-blue text-RegionalBank-blue'
						: 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}"
				>
					Manual Scoring
				</button>
			</nav>

			<!-- Load Test Action Button (only show on loadtest tab) -->
			{#if activeTab === 'loadtest'}
				<div class="pb-2">
					{#if loadTestRunning}
						<button
							on:click={() => loadTestDashboard?.stopTest()}
							class="px-6 py-2.5 bg-red-600 hover:bg-red-700 text-white font-semibold rounded-lg transition-colors shadow-sm"
						>
							Stop Test
						</button>
					{:else}
						<button
							on:click={() => loadTestDashboard?.startTest()}
							class="px-6 py-2.5 bg-green-600 hover:bg-green-700 text-white font-semibold rounded-lg transition-colors shadow-sm"
						>
							Start Load Test
						</button>
					{/if}
				</div>
			{/if}
		</div>
	</div>

	<!-- Tab Content -->
	{#if activeTab === 'loadtest'}
		<LoadTestDashboard bind:this={loadTestDashboard} bind:isRunning={loadTestRunning} {insertMode} />
	{:else}
		<!-- Manual Scoring Form -->
		<div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
			<!-- Form -->
			<div>
				<ScoreForm on:submit={handleSubmit} />
			</div>

			<!-- Result -->
			<div>
				{#if loading}
					<div class="card flex items-center justify-center py-20">
						<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-RegionalBank-blue"></div>
					</div>
				{:else if error}
					<div class="card bg-red-50 border border-red-200">
						<h2 class="text-xl font-bold text-red-800 mb-2">Error</h2>
						<p class="text-red-700">{error}</p>
					</div>
				{:else if result}
					<ScoreResult {result} {lookupMode} />
				{:else}
					<div class="card bg-gray-50 text-center py-20">
						<div class="text-gray-400 text-lg">
							Submit a transaction to see the fraud score
						</div>
						<p class="text-gray-500 text-sm mt-2">
							The V2 scoring engine evaluates 31 rules across blacklist, velocity, amount, behavioral, and pattern categories.
						</p>
					</div>
				{/if}
			</div>
		</div>

		<!-- Performance Target (only show on manual tab) -->
		<div class="card bg-RegionalBank-light">
			<h3 class="font-semibold text-RegionalBank-blue mb-2">Performance Target</h3>
			<p class="text-gray-700">
				End-to-end scoring must complete in <strong>&lt;50ms</strong>. This includes:
			</p>
			<div class="mt-2 grid grid-cols-1 md:grid-cols-3 gap-2 text-sm text-gray-600">
				<div>
					<span class="font-medium text-amber-600">Phase 1 — DB Read:</span>
					<ul class="ml-4 mt-1 space-y-0.5">
						<li>- Customer fetch (features + cache)</li>
						<li>- Txn lookups (if LOOKUP_MODE=db)</li>
					</ul>
				</div>
				<div>
					<span class="font-medium text-green-600">Phase 2 — Rules:</span>
					<ul class="ml-4 mt-1 space-y-0.5">
						<li>- 31 rules evaluated (CPU only)</li>
					</ul>
				</div>
				<div>
					<span class="font-medium text-purple-600">Phase 3 — DB Write:</span>
					<ul class="ml-4 mt-1 space-y-0.5">
						<li>- Customer update</li>
						<li>- Transaction insert (if insert_mode=sync)</li>
					</ul>
				</div>
			</div>
		</div>
	{/if}
</div>
