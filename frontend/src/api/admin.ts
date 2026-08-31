import { apiDelete, apiDeleteJson, apiGet, apiPatchJson, apiPostJson, apiPutJson } from './client'

export type AdminUser = {
  id: string
  username: string
  email: string | null
  enabled: boolean
  role_names: string[]
  group_names: string[]
  created_at: string
  updated_at: string
}

export type AdminUserList = {
  items: AdminUser[]
  total: number
  limit: number
  offset: number
}

export type AdminRole = {
  id: string
  name: string
  description: string | null
  is_system: boolean
  created_at: string
  updated_at: string
}

export type AdminRoleList = {
  items: AdminRole[]
  total: number
}

export type AdminGroup = {
  id: string
  name: string
  path: string | null
  is_system: boolean
  created_at: string
  updated_at: string
}

export type AdminGroupList = {
  items: AdminGroup[]
  total: number
}

export type UserCreateBody = {
  username: string
  email?: string | null
  password: string
  enabled?: boolean
  role_names: string[]
  group_names: string[]
}

export type UserUpdateBody = {
  email?: string | null
  enabled?: boolean
  password?: string
  role_names?: string[]
  group_names?: string[]
}

export type AccessPreview = {
  principal_type: 'role' | 'group'
  principal_id: string
  principal_name: string
  permission: string
}

export type AdminFile = {
  id: string
  display_name: string
  file_type: string
  size_bytes: number
  object_store_path: string
  uploaded_at: string
  updated_at: string
  access_total?: number
  access_preview?: AccessPreview[]
}

export type AdminFileList = {
  items: AdminFile[]
  total: number
  limit: number
  offset: number
}

export type ListAdminFilesParams = {
  limit?: number
  offset?: number
  q?: string
  has_acl?: boolean | null
}

export type AclGrant = {
  id: string
  principal_type: 'role' | 'group'
  principal_id: string
  principal_name: string
  permission: string
}

export type AclGrantInput = {
  principal_type: 'role' | 'group'
  principal_id: string
  permission: 'viewer' | 'editor'
}

export type FileAclResponse = {
  file_id: string
  grants: AclGrant[]
  acl_job_id: string | null
}

export type BulkAclMode = 'upsert' | 'replace' | 'revoke'

export type BulkAclRequest = {
  file_ids: string[]
  mode: BulkAclMode
  grants: AclGrantInput[]
  confirm_replace?: boolean
}

export type BulkAclResult = {
  file_id: string
  grants: AclGrant[]
  acl_job_id: string | null
}

export type BulkAclFailed = {
  file_id: string
  error: string
}

export type BulkAclResponse = {
  results: BulkAclResult[]
  failed: BulkAclFailed[]
}

export type FileGrantItem = {
  acl_id: string
  file_id: string
  display_name: string
  file_type: string
  permission: string
  updated_at: string
}

export type FileGrantList = {
  items: FileGrantItem[]
  total: number
  limit: number
  offset: number
}

export type AclJob = {
  id: string
  file_id: string
  status: string
  total_chunks: number | null
  updated_chunks: number | null
  error: string | null
  created_by_user_id: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
}

export async function listUsers(limit = 50, offset = 0, q?: string): Promise<AdminUserList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (q?.trim()) params.set('q', q.trim())
  return apiGet<AdminUserList>(`/admin/users?${params}`)
}

export async function createUser(body: UserCreateBody): Promise<AdminUser> {
  return apiPostJson<AdminUser>('/admin/users', body)
}

export async function updateUser(id: string, body: UserUpdateBody): Promise<AdminUser> {
  return apiPatchJson<AdminUser>(`/admin/users/${id}`, body)
}

export async function listRoles(includeSystem = false): Promise<AdminRoleList> {
  return apiGet<AdminRoleList>(`/admin/roles?include_system=${includeSystem}`)
}

export async function createRole(name: string, description?: string | null): Promise<AdminRole> {
  return apiPostJson<AdminRole>('/admin/roles', { name, description: description ?? null })
}

export async function updateRole(id: string, description: string | null): Promise<AdminRole> {
  return apiPatchJson<AdminRole>(`/admin/roles/${id}`, { description })
}

export async function deleteRole(id: string): Promise<void> {
  return apiDelete(`/admin/roles/${id}`)
}

export async function listGroups(includeSystem = false): Promise<AdminGroupList> {
  return apiGet<AdminGroupList>(`/admin/groups?include_system=${includeSystem}`)
}

export async function createGroup(name: string): Promise<AdminGroup> {
  return apiPostJson<AdminGroup>('/admin/groups', { name })
}

export async function deleteGroup(id: string): Promise<void> {
  return apiDelete(`/admin/groups/${id}`)
}

export type MembersMutationResponse = {
  results: AdminUser[]
  failed: { user_id: string; error: string }[]
}

export async function listRoleMembers(
  roleId: string,
  limit = 50,
  offset = 0,
  q?: string,
): Promise<AdminUserList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (q?.trim()) params.set('q', q.trim())
  return apiGet<AdminUserList>(`/admin/roles/${roleId}/members?${params}`)
}

export async function addRoleMembers(
  roleId: string,
  userIds: string[],
): Promise<MembersMutationResponse> {
  return apiPostJson<MembersMutationResponse>(`/admin/roles/${roleId}/members`, {
    user_ids: userIds,
  })
}

export async function removeRoleMembers(
  roleId: string,
  userIds: string[],
): Promise<MembersMutationResponse> {
  return apiPostJson<MembersMutationResponse>(`/admin/roles/${roleId}/members:remove`, {
    user_ids: userIds,
  })
}

export async function listGroupMembers(
  groupId: string,
  limit = 50,
  offset = 0,
  q?: string,
): Promise<AdminUserList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (q?.trim()) params.set('q', q.trim())
  return apiGet<AdminUserList>(`/admin/groups/${groupId}/members?${params}`)
}

export async function addGroupMembers(
  groupId: string,
  userIds: string[],
): Promise<MembersMutationResponse> {
  return apiPostJson<MembersMutationResponse>(`/admin/groups/${groupId}/members`, {
    user_ids: userIds,
  })
}

export async function removeGroupMembers(
  groupId: string,
  userIds: string[],
): Promise<MembersMutationResponse> {
  return apiPostJson<MembersMutationResponse>(`/admin/groups/${groupId}/members:remove`, {
    user_ids: userIds,
  })
}

export async function listAdminFiles(params: ListAdminFilesParams = {}): Promise<AdminFileList> {
  const { limit = 100, offset = 0, q, has_acl } = params
  const search = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (q?.trim()) search.set('q', q.trim())
  if (has_acl === true) search.set('has_acl', 'true')
  if (has_acl === false) search.set('has_acl', 'false')
  return apiGet<AdminFileList>(`/admin/files?${search}`)
}

export async function getFileAcl(fileId: string): Promise<FileAclResponse> {
  return apiGet<FileAclResponse>(`/admin/files/${fileId}/acl`)
}

export async function replaceFileAcl(
  fileId: string,
  grants: AclGrantInput[],
): Promise<FileAclResponse> {
  return apiPutJson<FileAclResponse>(`/admin/files/${fileId}/acl`, { grants })
}

export async function deleteFileAcl(fileId: string, aclId: string): Promise<FileAclResponse> {
  return apiDeleteJson<FileAclResponse>(`/admin/files/${fileId}/acl/${aclId}`)
}

export async function bulkFileAcl(body: BulkAclRequest): Promise<BulkAclResponse> {
  return apiPostJson<BulkAclResponse>('/admin/files/acl:bulk', body)
}

export async function listRoleFileGrants(
  roleId: string,
  limit = 50,
  offset = 0,
): Promise<FileGrantList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  return apiGet<FileGrantList>(`/admin/roles/${roleId}/file-grants?${params}`)
}

export async function listGroupFileGrants(
  groupId: string,
  limit = 50,
  offset = 0,
): Promise<FileGrantList> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  return apiGet<FileGrantList>(`/admin/groups/${groupId}/file-grants?${params}`)
}

export async function getAclJob(jobId: string): Promise<AclJob> {
  return apiGet<AclJob>(`/admin/acl-jobs/${jobId}`)
}

export async function retryAclJob(jobId: string): Promise<AclJob> {
  return apiPostJson<AclJob>(`/admin/acl-jobs/${jobId}/retry`, {})
}
