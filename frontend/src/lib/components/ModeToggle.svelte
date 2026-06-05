<script lang="ts">
	import type { UpdateMode, InsertMode } from '$lib/types';
	import { getUpdateMode, setUpdateMode, getLookupMode, setLookupMode, getInsertMode, setInsertMode } from '$lib/api';
	import { onMount, createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher<{ lookupModeChange: 'memory' | 'db'; insertModeChange: InsertMode }>();

	let updateMode: UpdateMode = 'standard';
	let lookupMode: 'memory' | 'db' = 'memory';
	let insertMode: InsertMode = 'sync';
	let at6Label = '';
	let dbOpsLabel = '';
	let insertLabel = '';
	let loading = false;
	let errorMsg = '';

	const updateModeOptions: { value: UpdateMode; label: string }[] = [
		{ value: 'standard', label: 'Standard' },
		{ value: 'pipeline', label: 'Pipeline' },
		{ value: 'aggregation', label: 'Aggregation' }
	];

	const lookupModeOptions: { value: 'memory' | 'db'; label: string }[] = [
		{ value: 'memory', label: 'Memory' },
		{ value: 'db', label: 'DB' }
	];

	const insertModeOptions: { value: InsertMode; label: string }[] = [
		{ value: 'sync', label: 'Sync' },
		{ value: 'none', label: 'None' }
	];

	function updateSubtitles() {
		const at6Map: Record<UpdateMode, string> = {
			standard: 'at6: app-side math',
			pipeline: 'at6: server-side pipeline',
			aggregation: 'at6: server-side $stdDevPop'
		};
		at6Label = at6Map[updateMode];

		let ops = lookupMode === 'memory' ? 1 : 2;  // read customer + (optional bl/txn lookups)
		if (insertMode === 'sync') ops += 2;  // update customer + insert txn
		else ops += 1;  // update customer only
		dbOpsLabel = `${ops} DB ops / txn`;

		const insertMap: Record<InsertMode, string> = {
			sync: 'Insert scored txn to MongoDB',
			none: 'Pure scoring — no insert'
		};
		insertLabel = insertMap[insertMode];
	}

	onMount(async () => {
		try {
			const [uRes, lRes, iRes] = await Promise.all([getUpdateMode(), getLookupMode(), getInsertMode()]);
			updateMode = uRes.update_mode;
			lookupMode = lRes.lookup_mode;
			insertMode = iRes.insert_mode;
			updateSubtitles();
		} catch (e) {
			console.error('Failed to load config modes:', e);
		}
	});

	async function handleUpdateMode(mode: UpdateMode) {
		if (mode === updateMode || loading) return;
		const prev = updateMode;
		updateMode = mode;
		updateSubtitles();
		loading = true;
		errorMsg = '';
		try {
			const res = await setUpdateMode(mode);
			updateMode = res.update_mode;
			updateSubtitles();
		} catch {
			updateMode = prev;
			updateSubtitles();
			errorMsg = 'Failed to switch update mode';
			setTimeout(() => (errorMsg = ''), 3000);
		} finally {
			loading = false;
		}
	}

	async function handleLookupMode(mode: 'memory' | 'db') {
		if (mode === lookupMode || loading) return;
		const prev = lookupMode;
		lookupMode = mode;
		updateSubtitles();
		loading = true;
		errorMsg = '';
		try {
			const res = await setLookupMode(mode);
			lookupMode = res.lookup_mode;
			updateSubtitles();
			dispatch('lookupModeChange', lookupMode);
		} catch {
			lookupMode = prev;
			updateSubtitles();
			errorMsg = 'Failed to switch lookup mode';
			setTimeout(() => (errorMsg = ''), 3000);
		} finally {
			loading = false;
		}
	}

	async function handleInsertMode(mode: InsertMode) {
		if (mode === insertMode || loading) return;
		const prev = insertMode;
		insertMode = mode;
		updateSubtitles();
		loading = true;
		errorMsg = '';
		try {
			const res = await setInsertMode(mode);
			insertMode = res.insert_mode;
			updateSubtitles();
			dispatch('insertModeChange', insertMode);
		} catch {
			insertMode = prev;
			updateSubtitles();
			errorMsg = 'Failed to switch insert mode';
			setTimeout(() => (errorMsg = ''), 3000);
		} finally {
			loading = false;
		}
	}
</script>

<div class="rounded-lg border border-gray-200 bg-white px-5 py-4 shadow-sm">
	<div class="flex flex-col sm:flex-row sm:items-center sm:gap-8 gap-4">
		<!-- Header -->
		<div class="flex items-center gap-2 text-sm font-semibold text-gray-700 shrink-0">
			<svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
			</svg>
			Engine Configuration
		</div>

		<!-- Update Mode -->
		<div class="flex flex-col gap-1">
			<span class="text-xs font-medium text-gray-500 uppercase tracking-wide">Update Mode</span>
			<div class="inline-flex rounded-lg border border-gray-300 overflow-hidden">
				{#each updateModeOptions as opt}
					<button
						class="px-3 py-1.5 text-sm font-medium transition-colors {updateMode === opt.value
							? 'bg-[#003d79] text-white'
							: 'bg-gray-50 text-gray-600 hover:bg-gray-100'}"
						class:opacity-60={loading}
						on:click={() => handleUpdateMode(opt.value)}
						disabled={loading}
					>
						{opt.label}
					</button>
				{/each}
			</div>
			<span class="text-xs text-gray-500">{at6Label}</span>
		</div>

		<!-- Lookup Mode -->
		<div class="flex flex-col gap-1">
			<span class="text-xs font-medium text-gray-500 uppercase tracking-wide">Lookup Mode</span>
			<div class="inline-flex rounded-lg border border-gray-300 overflow-hidden">
				{#each lookupModeOptions as opt}
					<button
						class="px-3 py-1.5 text-sm font-medium transition-colors {lookupMode === opt.value
							? 'bg-[#003d79] text-white'
							: 'bg-gray-50 text-gray-600 hover:bg-gray-100'}"
						class:opacity-60={loading}
						on:click={() => handleLookupMode(opt.value)}
						disabled={loading}
					>
						{opt.label}
					</button>
				{/each}
			</div>
			<span class="text-xs text-gray-500">{dbOpsLabel}</span>
		</div>

		<!-- Insert Mode -->
		<div class="flex flex-col gap-1">
			<span class="text-xs font-medium text-gray-500 uppercase tracking-wide">Insert Mode</span>
			<div class="inline-flex rounded-lg border border-gray-300 overflow-hidden">
				{#each insertModeOptions as opt}
					<button
						class="px-3 py-1.5 text-sm font-medium transition-colors {insertMode === opt.value
							? 'bg-[#003d79] text-white'
							: 'bg-gray-50 text-gray-600 hover:bg-gray-100'}"
						class:opacity-60={loading}
						on:click={() => handleInsertMode(opt.value)}
						disabled={loading}
					>
						{opt.label}
					</button>
				{/each}
			</div>
			<span class="text-xs text-gray-500">{insertLabel}</span>
		</div>

		<!-- Error toast -->
		{#if errorMsg}
			<span class="text-xs text-red-600 font-medium">{errorMsg}</span>
		{/if}
	</div>
</div>
