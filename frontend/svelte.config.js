import adapterNode from '@sveltejs/adapter-node';
import adapterStatic from '@sveltejs/adapter-static';

// STATIC=1: serverless demo for GitHub Pages (data from static/data, maths in the browser).
// BASE_PATH: sub-path it is served from, e.g. /football-predictor.
const isStatic = process.env.STATIC === '1';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		adapter: isStatic ? adapterStatic({ fallback: 'index.html' }) : adapterNode({ out: 'build' }),
		paths: { base: isStatic ? (process.env.BASE_PATH ?? '') : '' }
	}
};

export default config;
