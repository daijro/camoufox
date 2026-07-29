/** @deprecated Use @/types/console + @/stores/data */
export type { Profile, ProfileStatus } from '@/types/console'
export { countRunning } from '@/types/console'

import { useDataStore } from '@/stores/data'

export async function fetchProfiles() {
  await new Promise((r) => setTimeout(r, 50))
  return useDataStore.getState().profiles.filter((p) => !p.deletedAt)
}
