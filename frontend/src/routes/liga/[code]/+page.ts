import { error } from '@sveltejs/kit';
import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
  const leagues = await api.leagues(fetch);
  const league = leagues.find((l) => l.code === params.code);
  if (!league) error(404, `Liga desconocida: ${params.code}`);
  const [table, ratings, fixtures, forecast] = await Promise.all([
    api.table(params.code, fetch),
    api.ratings(params.code, fetch),
    api.fixtures(params.code, 20, fetch).catch(() => []),
    league.has_fixtures ? api.forecast(params.code, fetch).catch(() => null) : Promise.resolve(null),
  ]);
  return { leagues, league, table, ratings, fixtures, forecast };
};
