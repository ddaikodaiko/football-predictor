import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
  const [value, clv, leagues] = await Promise.all([api.value(0.02, fetch), api.clv(fetch), api.leagues(fetch)]);
  return { value, clv, leagues };
};
