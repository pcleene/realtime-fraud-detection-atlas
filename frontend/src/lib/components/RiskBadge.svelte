<script lang="ts">
	import type { RiskLevel } from '$lib/types';

	export let level: RiskLevel;
	export let score: number;
	export let small = false;

	$: colorClass = {
		low: 'risk-low',
		medium: 'risk-medium',
		high: 'risk-high'
	}[level];

	$: labelText = {
		low: 'Low Risk',
		medium: 'Medium Risk',
		high: 'High Risk'
	}[level];

	$: shortLabel = {
		low: 'Low',
		medium: 'Medium',
		high: 'High'
	}[level];
</script>

{#if small}
	<div class="flex items-center gap-2">
		<span class="text-sm font-bold {level === 'high' ? 'text-red-600' : level === 'medium' ? 'text-yellow-600' : 'text-green-600'}">
			{score}
		</span>
		<span class="px-1.5 py-0.5 text-xs rounded font-medium {colorClass}">
			{shortLabel}
		</span>
	</div>
{:else}
	<div class="flex items-center gap-4">
		<div class="text-center">
			<div class="text-4xl font-bold {level === 'high' ? 'text-red-600' : level === 'medium' ? 'text-yellow-600' : 'text-green-600'}">
				{score}
			</div>
			<div class="text-sm text-gray-500">Risk Score</div>
		</div>
		<div class="px-4 py-2 rounded-lg border-2 font-semibold {colorClass}">
			{labelText}
		</div>
	</div>
{/if}
