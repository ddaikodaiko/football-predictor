import { env } from '$env/dynamic/public';

// The static demo is a single-page app: every page renders in the browser from JSON.
export const ssr = env.PUBLIC_STATIC !== '1';
