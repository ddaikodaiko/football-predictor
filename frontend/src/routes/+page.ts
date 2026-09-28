import { api, BIG_FIVE } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const leagues = await api.leagues(fetch);
  const fixtures = await Promise.all(
    BIG_FIVE.map(async (code) => ({ code, matches: await api.fixtures(code, 10, fetch).catch(() => []) })),
  );
  return { leagues, fixtures };
};
