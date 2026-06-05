/** @type {import('tailwindcss').Config} */
export default {
	content: ['./src/**/*.{html,js,svelte,ts}'],
	theme: {
		extend: {
			colors: {
				RegionalBank: {
					blue: '#003d79',
					gold: '#ffc72c',
					light: '#e8f4ff'
				}
			}
		}
	},
	plugins: []
};
