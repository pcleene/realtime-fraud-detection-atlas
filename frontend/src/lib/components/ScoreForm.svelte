<script lang="ts">
	import type { ScoreTransactionRequest } from '$lib/types';
	import { createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher<{ submit: ScoreTransactionRequest }>();

	// V2 form fields
	let customer_id = 'CUST-';
	let b2 = 'ACC-';         // destination account
	let c2 = '';              // destination name
	let n2 = 'Tokopedia';    // merchant description
	let at3 = 500000;         // amount
	let service = 0;          // service code
	let tp = 0;               // purpose code
	let h1 = '';              // device model
	let channel = 'Livin';
	let lat: number | null = -6.2088;
	let lon: number | null = 106.8456;

	const channels = ['Livin', 'KOPRA', 'ATM', 'QRIS', 'Branch', 'Ecom'];

	const merchants = [
		{ name: 'Tokopedia', n2: 'Tokopedia', service: 5311 },
		{ name: 'Shopee', n2: 'Shopee', service: 5311 },
		{ name: 'GoFood', n2: 'GoFood', service: 5812 },
		{ name: 'Gojek', n2: 'Gojek', service: 4121 },
		{ name: 'Indomaret', n2: 'Indomaret', service: 5411 },
		{ name: 'Telkomsel', n2: 'Telkomsel', service: 4814 },
		{ name: 'PLN', n2: 'PLN', service: 4900 }
	];

	function selectMerchant(m: typeof merchants[0]) {
		n2 = m.n2;
		service = m.service;
	}

	function handleSubmit() {
		const z1 = new Date().toISOString();
		const request: ScoreTransactionRequest = {
			customer_id,
			b2,
			at3,
			z1,
			channel,
			lat,
			lon
		};
		if (c2) request.c2 = c2;
		if (n2) request.n2 = n2;
		if (service) request.service = service;
		if (tp) request.tp = tp;
		if (h1) request.h1 = h1;
		dispatch('submit', request);
	}

	function generateRandomIds() {
		const hex = () => Math.random().toString(16).substring(2, 8).toUpperCase();
		customer_id = `CUST-${hex()}${hex().substring(0, 6)}`;
		b2 = `ACC-${hex()}`;
		h1 = `DEV-${hex()}`;
	}
</script>

<form on:submit|preventDefault={handleSubmit} class="card space-y-6">
	<div class="flex items-center justify-between">
		<h2 class="text-xl font-bold text-gray-900">Score Transaction</h2>
		<button type="button" on:click={generateRandomIds} class="btn btn-secondary text-sm">
			Generate Random IDs
		</button>
	</div>

	<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
		<!-- Customer Info -->
		<div class="space-y-4">
			<h3 class="font-semibold text-gray-700 border-b pb-2">Customer Info</h3>

			<div>
				<label class="label" for="customer_id">Customer ID</label>
				<input
					id="customer_id"
					type="text"
					class="input font-mono"
					bind:value={customer_id}
					placeholder="CUST-XXXXXXXXXXXX"
					pattern="CUST-[A-F0-9]{'{'}12{'}'}"
					required
				/>
			</div>

			<div>
				<label class="label" for="b2">Destination Account</label>
				<input
					id="b2"
					type="text"
					class="input font-mono"
					bind:value={b2}
					placeholder="ACC-XXXXXXXX"
					required
				/>
			</div>

			<div>
				<label class="label" for="c2">Destination Name</label>
				<input
					id="c2"
					type="text"
					class="input"
					bind:value={c2}
					placeholder="Recipient name (optional)"
				/>
			</div>
		</div>

		<!-- Transaction Details -->
		<div class="space-y-4">
			<h3 class="font-semibold text-gray-700 border-b pb-2">Transaction Details</h3>

			<div>
				<label class="label" for="at3">Amount (IDR)</label>
				<input
					id="at3"
					type="number"
					class="input"
					bind:value={at3}
					min="1000"
					step="1000"
					required
				/>
			</div>

			<div>
				<label class="label" for="channel">Channel</label>
				<select id="channel" class="input" bind:value={channel}>
					{#each channels as ch}
						<option value={ch}>{ch}</option>
					{/each}
				</select>
			</div>

			<div class="grid grid-cols-2 gap-2">
				<div>
					<label class="label" for="service">Service Code</label>
					<input
						id="service"
						type="number"
						class="input"
						bind:value={service}
					/>
				</div>
				<div>
					<label class="label" for="tp">Purpose Code</label>
					<input
						id="tp"
						type="number"
						class="input"
						bind:value={tp}
					/>
				</div>
			</div>
		</div>

		<!-- Location -->
		<div class="space-y-4">
			<h3 class="font-semibold text-gray-700 border-b pb-2">Location</h3>

			<div class="grid grid-cols-2 gap-2">
				<div>
					<label class="label" for="lat">Latitude</label>
					<input
						id="lat"
						type="number"
						class="input"
						bind:value={lat}
						step="0.0001"
					/>
				</div>
				<div>
					<label class="label" for="lon">Longitude</label>
					<input
						id="lon"
						type="number"
						class="input"
						bind:value={lon}
						step="0.0001"
					/>
				</div>
			</div>
			<p class="text-xs text-gray-500">Default: Jakarta (-6.2088, 106.8456)</p>
		</div>

		<!-- Merchant -->
		<div class="space-y-4">
			<h3 class="font-semibold text-gray-700 border-b pb-2">Merchant</h3>

			<div class="flex flex-wrap gap-2">
				{#each merchants as m}
					<button
						type="button"
						class="px-3 py-1 text-sm rounded-full transition-colors {n2 === m.n2 ? 'bg-RegionalBank-blue text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}"
						on:click={() => selectMerchant(m)}
					>
						{m.name}
					</button>
				{/each}
			</div>

			<div>
				<label class="label" for="n2">Merchant Description</label>
				<input
					id="n2"
					type="text"
					class="input"
					bind:value={n2}
					placeholder="Merchant/beneficiary description"
				/>
			</div>
		</div>

		<!-- Device -->
		<div class="space-y-4 md:col-span-2">
			<h3 class="font-semibold text-gray-700 border-b pb-2">Device Info</h3>

			<div>
				<label class="label" for="h1">Device Model</label>
				<input
					id="h1"
					type="text"
					class="input font-mono"
					bind:value={h1}
					placeholder="e.g. Samsung Galaxy S24 (optional)"
				/>
			</div>
		</div>
	</div>

	<div class="pt-4 border-t">
		<button type="submit" class="btn btn-primary w-full py-3 text-lg">
			Score Transaction
		</button>
	</div>
</form>
