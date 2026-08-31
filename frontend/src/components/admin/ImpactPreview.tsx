type Props = {
  text: string
}

export function ImpactPreview({ text }: Props) {
  return <p className="rounded-md border border-slate-800 bg-slate-900/50 px-3 py-2 text-sm text-slate-300">{text}</p>
}

export function buildGrantImpact(
  mode: 'upsert' | 'replace',
  permission: 'viewer' | 'editor',
  principalNames: string[],
  fileCount: number,
): string {
  const perm = permission === 'editor' ? 'Editor' : 'Viewer'
  const names = principalNames.join(', ') || 'selected roles/groups'
  const jobs = `up to ${fileCount} search-index sync job${fileCount === 1 ? '' : 's'}`
  if (mode === 'replace') {
    return `Replace all access with ${perm} for ${names} on ${fileCount} file${fileCount === 1 ? '' : 's'} (${jobs}).`
  }
  return `Add or update ${perm} for ${names} on ${fileCount} file${fileCount === 1 ? '' : 's'} (${jobs}).`
}

export function buildRevokeImpact(principalNames: string[], fileCount: number): string {
  const names = principalNames.join(', ') || 'selected roles/groups'
  return `Remove ${names} from ${fileCount} file${fileCount === 1 ? '' : 's'} (up to ${fileCount} search-index sync job${fileCount === 1 ? '' : 's'}).`
}

export function buildAddMembersImpact(
  kind: 'role' | 'group',
  name: string,
  userCount: number,
): string {
  return `Add ${kind} ${name} to ${userCount} user${userCount === 1 ? '' : 's'}.`
}

export const TOKEN_REFRESH_NOTICE =
  'Users must refresh their session (re-login) before search reflects new roles/groups.'
