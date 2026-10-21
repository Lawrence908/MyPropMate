import { Link } from 'react-router-dom'
import type { Overview } from '../api'
import { label } from '../api'
import { Badge, Empty, PageHeader } from '../components'
import { useApp, useData } from '../hooks'

const OPEN_TASK = ['todo', 'doing', 'waiting']
const ACTIVE_LEAD = ['contacted', 'replied', 'interested', 'viewing', 'applied', 'approved']

const sum = (rec: Record<string, number>, keys: string[]) => keys.reduce((n, k) => n + (rec[k] ?? 0), 0)

export default function OverviewPage() {
  const { data, error } = useData<Overview>('/api/overview')
  const { setPropertyId } = useApp()

  if (error) return <div className="error">{error}</div>
  if (!data) return <p className="muted">Loading…</p>

  const { payments } = data
  return (
    <>
      <PageHeader title="Overview" sub="Everything that needs you, across every property." />

      <section className="stat-row">
        <Link to="/payments" className={`stat ${payments.pending ? 'attention' : ''}`}>
          <span className="stat-n">{payments.pending}</span>
          <span>receipts awaiting confirmation</span>
        </Link>
        <Link to="/payments" className={`stat ${payments.failed ? 'warn' : ''}`}>
          <span className="stat-n">{payments.failed}</span>
          <span>payments flagged</span>
        </Link>
        <Link to="/payments" className="stat">
          <span className="stat-n">{payments.sent}</span>
          <span>receipts sent</span>
        </Link>
      </section>

      <h2 className="section-title">Properties</h2>
      {data.properties.length === 0 ? (
        <Empty>
          No properties yet. <Link to="/properties">Add your first property</Link> to start tracking
          tasks, leads and posts.
        </Empty>
      ) : (
        <div className="cards">
          {data.properties.map((p) => {
            const c = p.counts
            const open = sum(c.tasks, OPEN_TASK)
            const done = c.tasks.done ?? 0
            const leads = sum(c.prospects, ACTIVE_LEAD)
            const toContact = c.prospects.to_contact ?? 0
            return (
              <article key={p.id} className="card">
                <header>
                  <div>
                    <h3>{p.name}</h3>
                    <p className="muted">{[p.address, p.city, p.province].filter(Boolean).join(', ')}</p>
                  </div>
                  <Badge value={p.status} />
                </header>
                <dl className="kv">
                  <div>
                    <dt>Tenants</dt>
                    <dd>{c.tenants}</dd>
                  </div>
                  <div>
                    <dt>Open tasks</dt>
                    <dd>
                      {open}
                      {open + done > 0 && <span className="muted"> / {open + done}</span>}
                    </dd>
                  </div>
                  <div>
                    <dt>Active leads</dt>
                    <dd>{leads}</dd>
                  </div>
                  <div>
                    <dt>To contact</dt>
                    <dd>{toContact}</dd>
                  </div>
                  <div>
                    <dt>Posts live</dt>
                    <dd>{c.posts.posted ?? 0}</dd>
                  </div>
                  <div>
                    <dt>Posts ready</dt>
                    <dd>{(c.posts.ready ?? 0) + (c.posts.draft ?? 0)}</dd>
                  </div>
                </dl>
                {Object.keys(c.prospects).length > 0 && (
                  <p className="muted small">
                    {Object.entries(c.prospects)
                      .map(([k, n]) => `${n} ${label(k).toLowerCase()}`)
                      .join(' · ')}
                  </p>
                )}
                <footer>
                  <Link to="/tasks" onClick={() => setPropertyId(p.id)}>Tasks</Link>
                  <Link to="/leads" onClick={() => setPropertyId(p.id)}>Leads</Link>
                  <Link to="/posts" onClick={() => setPropertyId(p.id)}>Posts</Link>
                </footer>
              </article>
            )
          })}
        </div>
      )}
    </>
  )
}
