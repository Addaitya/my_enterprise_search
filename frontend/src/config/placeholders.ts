export type ConnectorField = {
  key: string
  label: string
  kind?: 'text' | 'toggle' | 'textarea'
}

export type ConnectorCatalogEntry = {
  type: string
  label: string
  icon: string
  fields: ConnectorField[]
}

export type ConnectorFixture = {
  id: string
  type: string
  name: string
  enabled: boolean
  schedule: string
  cdc: boolean
  values: Record<string, string>
}

const text = (key: string, label: string): ConnectorField => ({ key, label })

export const CONNECTOR_CATALOG: ConnectorCatalogEntry[] = [
  {
    type: 'postgresql',
    label: 'PostgreSQL',
    icon: '🐘',
    fields: [text('host', 'Host'), text('port', 'Port'), text('database', 'Database'), text('username', 'Username'), text('password', 'Password'), text('schema', 'Schema')],
  },
  {
    type: 'oracle',
    label: 'Oracle DB',
    icon: '🔶',
    fields: [text('host', 'Host'), text('port', 'Port'), text('service_name', 'Service name'), text('username', 'Username'), text('password', 'Password')],
  },
  {
    type: 'sqlserver',
    label: 'SQL Server',
    icon: '🪟',
    fields: [text('host', 'Host'), text('port', 'Port'), text('database', 'Database'), text('username', 'Username'), text('password', 'Password')],
  },
  {
    type: 'sharepoint',
    label: 'SharePoint Online',
    icon: '📋',
    fields: [text('tenant_id', 'Tenant id'), text('client_id', 'Client id'), text('client_secret', 'Client secret'), text('site_url', 'Site URL')],
  },
  {
    type: 'salesforce',
    label: 'Salesforce',
    icon: '☁️',
    fields: [text('username', 'Username'), text('password', 'Password'), text('security_token', 'Security token'), text('instance_url', 'Instance URL')],
  },
  {
    type: 's3',
    label: 'Amazon S3',
    icon: '🪣',
    fields: [text('access_key', 'Access key'), text('secret_key', 'Secret key'), text('bucket', 'Bucket'), text('region', 'Region'), text('prefix', 'Prefix')],
  },
  {
    type: 'azure',
    label: 'Azure Blob Storage',
    icon: '🔷',
    fields: [text('account_name', 'Account name'), text('account_key', 'Account key'), text('container', 'Container'), text('prefix', 'Prefix')],
  },
  {
    type: 'gcs',
    label: 'Google Cloud Storage',
    icon: '🌐',
    fields: [text('project_id', 'Project id'), text('credentials_json', 'Credentials JSON'), text('bucket', 'Bucket'), text('prefix', 'Prefix')],
  },
  {
    type: 'email',
    label: 'Email / Exchange',
    icon: '📧',
    fields: [text('server', 'Server'), text('port', 'Port'), text('username', 'Username'), text('password', 'Password'), text('mailbox', 'Mailbox'), text('protocol', 'Protocol')],
  },
  {
    type: 'box',
    label: 'Box AI',
    icon: '📦',
    fields: [
      text('client_id', 'Client id'),
      text('client_secret', 'Client secret'),
      text('enterprise_id', 'Enterprise id'),
      { key: 'box_ai_enabled', label: 'Box AI', kind: 'toggle' },
      { key: 'ai_prompt_template', label: 'AI prompt template', kind: 'textarea' },
      text('folder_id', 'Folder id'),
    ],
  },
  {
    type: 'sap',
    label: 'SAP',
    icon: '🔷',
    fields: [
      text('host', 'Host'),
      text('instance_number', 'Instance number'),
      text('system_id', 'System id'),
      text('client', 'Client'),
      text('username', 'Username'),
      text('password', 'Password'),
      text('logon_group', 'Logon group'),
      text('message_server', 'Message server'),
      text('sap_router', 'SAP router'),
      text('rfc_destination', 'RFC destination'),
      text('language', 'Language'),
      { key: 'use_sapgui', label: 'Use SAP GUI', kind: 'toggle' },
    ],
  },
]

export const CONFIG_SECTIONS = [
  { id: 'ingestion', label: 'Ingestion', icon: '📥' },
  { id: 'messaging', label: 'Messaging', icon: '📨' },
  { id: 'etl', label: 'ETL', icon: '⚙️' },
  { id: 'parsing', label: 'Parsing', icon: '📄' },
  { id: 'enrichment', label: 'Enrichment', icon: '🧠' },
  { id: 'metadata', label: 'Metadata', icon: '🧬' },
  { id: 'ml', label: 'ML Classify', icon: '🤖' },
  { id: 'search', label: 'Search', icon: '🔍' },
  { id: 'iam', label: 'IAM', icon: '🔐' },
  { id: 'api', label: 'API', icon: '🌐' },
  { id: 'observability', label: 'Observability', icon: '📊' },
  { id: 'orchestration', label: 'Orchestration', icon: '☸️' },
] as const

export type ConfigSectionId = (typeof CONFIG_SECTIONS)[number]['id']

function emptyValues(type: string): Record<string, string> {
  const entry = CONNECTOR_CATALOG.find((item) => item.type === type)
  const values: Record<string, string> = {}
  for (const field of entry?.fields ?? []) {
    values[field.key] = field.kind === 'toggle' ? 'false' : ''
  }
  return values
}

function fixture(id: string, type: string, name: string): ConnectorFixture {
  return {
    id,
    type,
    name,
    enabled: false,
    schedule: '',
    cdc: false,
    values: emptyValues(type),
  }
}

export const CONNECTOR_FIXTURES: ConnectorFixture[] = [
  fixture('postgresql-crm', 'postgresql', 'PostgreSQL CRM'),
  fixture('sharepoint', 'sharepoint', 'SharePoint'),
  fixture('email', 'email', 'Email'),
  fixture('s3', 's3', 'Amazon S3'),
  fixture('salesforce', 'salesforce', 'Salesforce'),
  fixture('oracle', 'oracle', 'Oracle'),
  fixture('box', 'box', 'Box'),
  fixture('sap', 'sap', 'SAP'),
]

export function isSensitiveField(key: string): boolean {
  return /password|secret|key|token/i.test(key)
}
