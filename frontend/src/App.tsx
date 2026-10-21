import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import type { Meta, Property } from './api'
import { AppContext, useData } from './hooks'
import OverviewPage from './pages/Overview'
import PropertiesPage from './pages/Properties'
import TasksPage from './pages/Tasks'
import PaymentsPage from './pages/Payments'
import LeadsPage from './pages/Leads'
import PostsPage from './pages/Posts'
import TemplatesPage from './pages/Templates'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/payments', label: 'Rent & receipts' },
  { to: '/tasks', label: 'Tasks' },
  { to: '/leads', label: 'Leads' },
  { to: '/posts', label: 'Listing posts' },
  { to: '/templates', label: 'Message templates' },
  { to: '/properties', label: 'Properties' },
]

const STORAGE_KEY = 'mpm.propertyId'

export default function App() {
  const { data: meta } = useData<Meta>('/api/meta')
  const props = useData<Property[]>('/api/properties')
  const [propertyId, setPropertyIdState] = useState<number | null>(() => {
    const v = localStorage.getItem(STORAGE_KEY)
    return v ? Number(v) : null
  })
  const [toast, setToast] = useState<{ msg: string; kind: 'ok' | 'err' } | null>(null)

  const setPropertyId = useCallback((id: number | null) => {
    setPropertyIdState(id)
    if (id === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(id))
  }, [])

  // Default to the only property when there is exactly one; drop a stale selection.
  useEffect(() => {
    const list = props.data
    if (!list) return
    if (propertyId !== null && !list.some((p) => p.id === propertyId)) setPropertyId(null)
    else if (propertyId === null && list.length === 1) setPropertyId(list[0].id)
  }, [props.data, propertyId, setPropertyId])

  const flash = useCallback((msg: string, kind: 'ok' | 'err' = 'ok') => {
    setToast({ msg, kind })
    window.setTimeout(() => setToast((t) => (t?.msg === msg ? null : t)), kind === 'err' ? 6000 : 2500)
  }, [])

  const ctx = useMemo(
    () => ({
      meta,
      properties: props.data ?? [],
      reloadProperties: props.reload,
      propertyId,
      setPropertyId,
      flash,
    }),
    [meta, props.data, props.reload, propertyId, setPropertyId, flash],
  )

  return (
    <AppContext.Provider value={ctx}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="mark" aria-hidden>
              ⌂
            </span>
            MyPropMate
          </div>
          <label className="prop-picker">
            <span>Property</span>
            <select
              value={propertyId ?? ''}
              onChange={(e) => setPropertyId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">All properties</option>
              {(props.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <nav>
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <a className="docs-link" href="/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
        </aside>
        <main className="content">
          {props.error && <div className="error">Could not reach the API: {props.error}</div>}
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/payments" element={<PaymentsPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/leads" element={<LeadsPage />} />
            <Route path="/posts" element={<PostsPage />} />
            <Route path="/templates" element={<TemplatesPage />} />
            <Route path="/properties" element={<PropertiesPage />} />
            <Route path="*" element={<OverviewPage />} />
          </Routes>
        </main>
        {toast && <div className={`toast ${toast.kind}`}>{toast.msg}</div>}
      </div>
    </AppContext.Provider>
  )
}
