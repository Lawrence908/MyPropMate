import { useState } from 'react'
import type { Payment, Tenant } from '../api'
import { api, money } from '../api'
import { Empty, PageHeader } from '../components'
import { useAction, useApp, useData } from '../hooks'

function state(p: Payment): 'sent' | 'pending' | 'failed' {
  if (p.invoice_no === null) return 'failed'
  return p.emailed ? 'sent' : 'pending'
}

export default function PaymentsPage() {
  const { propertyId, properties } = useApp()
  const payments = useData<Payment[]>('/api/payments')
  const tenants = useData<Tenant[]>('/api/tenants')
  const act = useAction()
  const [busy, setBusy] = useState(false)

  // Unassigned rows (and flagged payments, which have no tenant) show under
  // every property so they can still be found and assigned.
  const inScope = <T extends { property_id: number | null }>(rows: T[]) =>
    propertyId === null ? rows : rows.filter((r) => r.property_id === propertyId || r.property_id === null)

  const rows = inScope(payments.data ?? [])
  const pending = rows.filter((p) => state(p) === 'pending')

  return (
    <>
      <PageHeader
        title="Rent & receipts"
        sub="Receipts are prepared automatically from Interac deposits. Nothing is emailed until you confirm, here or in Telegram."
      >
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            await act(() => api.post('/api/payments/process'), 'Inbox checked', payments.reload)
            setBusy(false)
          }}
        >
          {busy ? 'Checking…' : 'Check inbox now'}
        </button>
      </PageHeader>

      {pending.length > 0 && (
        <div className="callout">
          {pending.length} receipt{pending.length > 1 ? 's' : ''} ready to send. Open the PDF to check
          it, then send.
        </div>
      )}

      <section>
        <h2 className="section-title">Payments</h2>
        {rows.length === 0 ? (
          <Empty>No payments yet.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Tenant</th>
                  <th>Period</th>
                  <th className="num">Amount</th>
                  <th>Invoice</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => {
                  const s = state(p)
                  return (
                    <tr key={p.reference_number} className={s === 'failed' ? 'row-warn' : ''}>
                      <td>{p.payment_date}</td>
                      <td>{p.tenant_name ?? <span className="muted">{p.sender_name}</span>}</td>
                      <td>{s === 'failed' ? <span className="warn-text">{p.period.replace('FAILED: ', '')}</span> : p.period}</td>
                      <td className="num">{money(p.amount)}</td>
                      <td>{p.invoice_no ?? ''}</td>
                      <td>
                        <span className={`badge badge-${s}`}>{s === 'pending' ? 'Awaiting confirm' : s === 'sent' ? 'Sent' : 'Flagged'}</span>
                      </td>
                      <td className="row-actions">
                        {p.receipt_path && (
                          <a className="button secondary" href={`/api/payments/${encodeURIComponent(p.reference_number)}/receipt`} target="_blank" rel="noreferrer">
                            PDF
                          </a>
                        )}
                        {s === 'pending' && (
                          <button
                            onClick={() => {
                              if (!confirm(`Email the ${p.period} receipt to ${p.tenant_name}?`)) return
                              act(async () => {
                                const r = await api.post<{ status: string; to?: string }>(
                                  `/api/payments/${encodeURIComponent(p.reference_number)}/send`,
                                )
                                if (r.status !== 'sent') throw new Error(`Not sent: ${r.status}`)
                              }, 'Receipt sent', payments.reload)
                            }}
                          >
                            Send
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h2 className="section-title">Tenants</h2>
        <p className="muted small">
          Rent, contact and bank-name matching come from <code>tenants.json</code>. The property
          assignment is set here.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Tenant</th>
                <th className="num">Rent</th>
                <th className="num">Parking</th>
                <th>Email</th>
                <th>Last invoice</th>
                <th>Property</th>
              </tr>
            </thead>
            <tbody>
              {inScope(tenants.data ?? []).map((t) => (
                <tr key={t.id}>
                  <td>{t.display_name}</td>
                  <td className="num">{money(t.monthly_rent)}</td>
                  <td className="num">{t.parking_fee ? money(t.parking_fee) : ''}</td>
                  <td>{t.email}</td>
                  <td>#{t.last_invoice_no}</td>
                  <td>
                    <select
                      value={t.property_id ?? ''}
                      onChange={(e) =>
                        act(
                          () =>
                            api.patch(`/api/tenants/${t.id}/property`, {
                              property_id: e.target.value ? Number(e.target.value) : null,
                            }),
                          'Tenant updated',
                          () => {
                            tenants.reload()
                            payments.reload()
                          },
                        )
                      }
                    >
                      <option value="">Unassigned</option>
                      {properties.map((pr) => (
                        <option key={pr.id} value={pr.id}>
                          {pr.name}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
