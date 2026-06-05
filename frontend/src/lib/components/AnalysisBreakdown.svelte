<script lang="ts">
	import type { RuleAnalysis } from '$lib/types';

	export let analysis: RuleAnalysis[];
	export let triggeredCount: number = 0;

	interface CategoryGroup {
		category: string;
		label: string;
		rules: RuleAnalysis[];
		triggeredInGroup: number;
	}

	const categoryLabels: Record<string, string> = {
		blacklist: 'Blacklist',
		device: 'Device',
		velocity: 'Velocity',
		amount: 'Amount',
		behavioral: 'Behavioral',
		pattern: 'Pattern'
	};

	const categoryOrder = ['blacklist', 'device', 'velocity', 'amount', 'behavioral', 'pattern'];

	$: groups = buildGroups(analysis);

	function buildGroups(rules: RuleAnalysis[]): CategoryGroup[] {
		const map = new Map<string, RuleAnalysis[]>();
		for (const rule of rules) {
			const cat = rule.category;
			if (!map.has(cat)) map.set(cat, []);
			map.get(cat)!.push(rule);
		}
		return categoryOrder
			.filter(cat => map.has(cat))
			.map(cat => {
				const catRules = map.get(cat)!;
				return {
					category: cat,
					label: categoryLabels[cat] || cat,
					rules: catRules,
					triggeredInGroup: catRules.filter(r => r.triggered).length
				};
			});
	}

	// Track which categories are expanded
	let expanded: Record<string, boolean> = {};

	$: {
		// Auto-expand categories that have triggered rules, collapse others
		const newExpanded: Record<string, boolean> = {};
		for (const g of groups) {
			// Preserve user override if they toggled, otherwise auto-expand if triggered
			if (expanded[g.category] !== undefined) {
				newExpanded[g.category] = expanded[g.category];
			} else {
				newExpanded[g.category] = g.triggeredInGroup > 0;
			}
		}
		expanded = newExpanded;
	}

	function toggleCategory(cat: string) {
		expanded = { ...expanded, [cat]: !expanded[cat] };
	}

	function formatRuleName(name: string): string {
		return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
	}

	function formatDetails(details: Record<string, unknown>): string {
		if (!details || Object.keys(details).length === 0) return '';
		const parts: string[] = [];
		for (const [key, val] of Object.entries(details)) {
			if (val === null || val === undefined) continue;
			const label = key.replace(/_/g, ' ');
			if (typeof val === 'number') {
				parts.push(`${label}: ${Number.isInteger(val) ? val : (val as number).toFixed(2)}`);
			} else if (typeof val === 'boolean') {
				parts.push(`${label}: ${val ? 'yes' : 'no'}`);
			} else {
				parts.push(`${label}: ${val}`);
			}
		}
		return parts.join(' | ');
	}
</script>

<div class="space-y-3">
	<div class="flex items-center justify-between">
		<h3 class="text-lg font-semibold text-gray-800">Rule Analysis</h3>
		<span class="text-sm text-gray-500">
			<span class="font-semibold {triggeredCount > 0 ? 'text-red-600' : 'text-green-600'}">{triggeredCount}</span>
			/ {analysis.length} triggered
		</span>
	</div>

	{#each groups as group}
		<div class="border rounded-lg overflow-hidden">
			<!-- Category header -->
			<button
				class="w-full flex items-center justify-between px-4 py-2.5 text-left transition-colors
					{group.triggeredInGroup > 0 ? 'bg-red-50 hover:bg-red-100' : 'bg-gray-50 hover:bg-gray-100'}"
				on:click={() => toggleCategory(group.category)}
			>
				<div class="flex items-center gap-2">
					<svg
						class="w-4 h-4 text-gray-500 transition-transform {expanded[group.category] ? 'rotate-90' : ''}"
						fill="none" stroke="currentColor" viewBox="0 0 24 24"
					>
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
					</svg>
					<span class="font-semibold text-gray-800">{group.label}</span>
					<span class="text-xs text-gray-500">({group.rules.length} rules)</span>
				</div>
				{#if group.triggeredInGroup > 0}
					<span class="px-2 py-0.5 text-xs font-semibold rounded-full bg-red-100 text-red-700">
						{group.triggeredInGroup} triggered
					</span>
				{:else}
					<span class="px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-700">
						clear
					</span>
				{/if}
			</button>

			<!-- Rules list (collapsible) -->
			{#if expanded[group.category]}
				<div class="divide-y divide-gray-100">
					{#each group.rules as rule}
						<div class="px-4 py-2.5 flex items-start justify-between {rule.triggered ? '' : 'opacity-50'}">
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2">
									<span class="text-xs font-mono text-gray-400">{rule.rule}</span>
									<span class="font-medium text-gray-900 text-sm">{formatRuleName(rule.name)}</span>
									{#if rule.triggered}
										<span class="px-1.5 py-0.5 text-xs font-medium rounded bg-red-100 text-red-700">
											triggered
										</span>
									{/if}
								</div>
								{#if rule.triggered && rule.details && Object.keys(rule.details).length > 0}
									<p class="text-xs text-gray-500 mt-0.5 truncate">{formatDetails(rule.details)}</p>
								{/if}
							</div>
							<span class="ml-3 text-sm font-semibold {rule.score > 0 ? 'text-red-600' : 'text-gray-300'}">
								+{rule.score}
							</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/each}
</div>
