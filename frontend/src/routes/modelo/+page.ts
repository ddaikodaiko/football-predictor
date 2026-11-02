import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const [backtest, leagues, track] = await Promise.all([
    api.backtest(fetch), api.leagues(fetch), api.track(fetch).catch(() => null),
  ]);
  return { backtest, leagues, track };
};
