import type { Profile, ProfileIn } from './types'

/** Full profile body. Partial updates still send every field so a save cannot drop one. */
export function toProfileIn(profile: Profile, patch: Partial<ProfileIn> = {}): ProfileIn {
  const { links: linkPatch, ...rest } = patch
  return {
    name: profile.name ?? '',
    email: profile.email ?? '',
    phone: profile.phone ?? '',
    location: profile.location ?? '',
    work_auth: profile.work_auth ?? '',
    work_eligible: profile.work_eligible ?? '',
    needs_sponsorship: profile.needs_sponsorship ?? '',
    gender: profile.gender ?? '',
    race: profile.race ?? '',
    disability: profile.disability ?? '',
    veteran: profile.veteran ?? '',
    target_role: profile.target_role ?? '',
    profile_confirmed: profile.profile_confirmed,
    auto_apply: profile.auto_apply,
    links: {
      github: profile.links?.github ?? '',
      linkedin: profile.links?.linkedin ?? '',
      portfolio: profile.links?.portfolio ?? '',
      ...linkPatch,
    },
    ...rest,
  }
}
