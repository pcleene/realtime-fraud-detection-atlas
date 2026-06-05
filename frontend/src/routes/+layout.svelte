<script lang="ts">
	import '../app.css';

	export let params: Record<string, string> = {};
</script>

<div class="min-h-screen">
	<header class="bg-RegionalBank-blue text-white shadow-lg">
		<div class="container mx-auto px-4 py-4">
			<div class="flex items-center justify-between">
				<div class="flex items-center gap-4">
					<h1 class="text-2xl font-bold">RegionalBank Fraud Detection</h1>
					<span class="px-2 py-1 text-xs font-medium bg-RegionalBank-gold text-RegionalBank-blue rounded">POC</span>
				</div>
				<div class="text-sm opacity-80">
					MongoDB Consolidated Architecture
				</div>
			</div>
		</div>
	</header>

	<main class="container mx-auto px-4 py-8">
		<slot />
	</main>

	<footer class="border-t mt-auto">
		<div class="container mx-auto px-4 py-4 text-center text-sm text-gray-500">
			Fraud Scoring POC - MongoDB as replacement for Redis (36 shards) + Oracle
		</div>
	</footer>
</div>
