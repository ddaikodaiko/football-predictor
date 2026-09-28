import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const [backtest, leagues] = await Promise.all([api.backtest(fetch), api.leagues(fetch)]);
  return { backtest, leagues };
};
