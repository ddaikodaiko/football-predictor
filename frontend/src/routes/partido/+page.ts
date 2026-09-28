import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
  const league = url.searchParams.get('liga') ?? 'SP1';
  const [leagues, teams] = await Promise.all([api.leagues(fetch), api.teams(league, fetch)]);
  const home = url.searchParams.get('local') ?? teams[0];
  const away = url.searchParams.get('visitante') ?? teams[1];
  let prediction = null;
  let error = '';
  try {
    prediction = await api.predict(league, home, away, fetch);
  } catch (e) {
    error = (e as Error).message;
  }
  return { leagues, league, teams, home, away, prediction, error };
};
