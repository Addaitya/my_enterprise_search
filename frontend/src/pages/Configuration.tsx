import { useState } from 'react'

import { IngestionSection } from '../components/config/IngestionSection'
import { AppShell } from '../components/layout/AppShell'
import { CONFIG_SECTIONS, type ConfigSectionId } from '../config/placeholders'

function notBuiltCopy(id: ConfigSectionId): string {
  if (id === 'search') {
    return 'This section is not built. Hybrid search weights stay 0.3 and 0.7 on the server.'
  }
  if (id === 'iam') {
    return 'This section is not built. It does not change the Keycloak realm or the PKCE client.'
  }
  return 'This section is not built.'
}

export function Configuration() {
  const [section, setSection] = useState<ConfigSectionId>('ingestion')
  const active = CONFIG_SECTIONS.find((item) => item.id === section) ?? CONFIG_SECTIONS[0]

  return (
    <AppShell>
      <section className="space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Configuration</h1>
          <p className="mt-1 text-sm text-gray-500">
            Local placeholder shell. Nothing here is saved to the server.
          </p>
        </div>
        <div className="flex flex-col gap-6 sm:flex-row">
          <nav className="flex w-full shrink-0 flex-row gap-1 overflow-x-auto sm:w-44 sm:flex-col">
            {CONFIG_SECTIONS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setSection(item.id)}
                className={`rounded-lg px-3 py-2 text-left text-sm whitespace-nowrap ${
                  item.id === section
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                {item.icon} {item.label}
              </button>
            ))}
          </nav>
          <div className="min-w-0 flex-1">
            {section === 'ingestion' ? (
              <IngestionSection />
            ) : (
              <div className="rounded-xl border border-gray-200 bg-white p-5">
                <h2 className="text-sm font-semibold text-gray-900">
                  {active.icon} {active.label}
                </h2>
                <p className="mt-2 text-sm text-gray-500">{notBuiltCopy(section)}</p>
              </div>
            )}
          </div>
        </div>
      </section>
    </AppShell>
  )
}
