import { useEffect, useState } from 'react'
import type { Message, Prospect, Template } from '../api'
import { api, day, label } from '../api'
import type { FieldSpec } from '../components'
import { Badge, CopyButton, Empty, Form, Modal, NeedProperty, PageHeader, Select } from '../components'
import { useAction, useApp, useData } from '../hooks'

const CLOSED = ['signed', 'declined', 'not_interested']

/** "Name | channel | contact | personal note" per line. */
function parseLines(text: string, channels: string[]) {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const [name, channel, contact, ...rest] = l.split(/\s*[|\t]\s*/)
      const ch = (channel ?? '').toLowerCase()
      return {
        name,
        channel: channels.includes(ch) ? ch : contact?.includes('@') ? 'email' : 'facebook',
        contact: contact ?? '',
        personal_note: rest.join(' '),
      }
    })
    .filter((p) => p.name)
}

export default function LeadsPage() {
  const { propertyId, meta } = useApp()
  const list = useData<Prospect[]>(propertyId ? `/api/prospects?property_id=${propertyId}` : null)
  const templates = useData<Template[]>('/api/templates')
  const act = useAction()
  const [selected, setSelected] = useState<number | null>(null)
  const [adding, setAdding] = useState<'one' | 'many' | null>(null)
  const [bulkDraft, setBulkDraft] = useState(false)
  const [filter, setFilter] = useState('active')
  const [q, setQ] = useState('')

  useEffect(() => setSelected(null), [propertyId])

  if (!propertyId) return (<><PageHeader title="Leads" /><NeedProperty /></>)

  const channels = meta?.channels ?? []
  const statuses = meta?.prospect_statuses ?? []
  const all = list.data ?? []
  const rows = all
    .filter((p) => (filter === 'all' ? true : filter === 'active' ? !CLOSED.includes(p.status) : p.status === filter))
    .filter((p) => !q || `${p.name} ${p.contact} ${p.source} ${p.notes}`.toLowerCase().includes(q.toLowerCase()))
  const tpls = (templates.data ?? []).filter((t) => t.property_id === null || t.property_id === propertyId)

  const fields: FieldSpec[] = [
    { key: 'name', label: 'Name' },
    { key: 'channel', label: 'Channel', type: 'select', options: channels },
    { key: 'contact', label: 'Contact', placeholder: 'Email, phone, or Facebook profile link' },
    { key: 'source', label: 'Source', placeholder: 'Personal contact, FB group post, referral…' },
    { key: 'status', label: 'Status', type: 'select', options: statuses },
    { key: 'personal_note', label: 'Personal opener', type: 'textarea', rows: 3, placeholder: 'Fills {personal_note} in templates' },
    { key: 'notes', label: 'Notes', type: 'textarea', rows: 4, placeholder: 'Unit, posting dates, what they asked about, screening notes' },
  ]

  const counts = statuses.map((s) => [s, all.filter((p) => p.status === s).length] as const).filter(([, n]) => n)

  return (
    <>
      <PageHeader title="Leads" sub="Prospective tenants: who you have reached out to, what you sent, and who replied.">
        <button className="secondary" onClick={() => setBulkDraft(true)} disabled={!tpls.length}>
          Draft for everyone to contact
        </button>
        <button className="secondary" onClick={() => setAdding('many')}>Paste a list</button>
        <button onClick={() => setAdding('one')}>Add lead</button>
      </PageHeader>

      {counts.length > 0 && (
        <div className="pipeline">
          {counts.map(([s, n]) => (
            <button key={s} className={`pill ${filter === s ? 'on' : ''}`} onClick={() => setFilter(filter === s ? 'active' : s)}>
              {label(s)} <b>{n}</b>
            </button>
          ))}
        </div>
      )}

      <div className="split">
        <div className="split-list">
          <div className="toolbar">
            <input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
            <Select
              value={filter}
              options={[{ value: 'active', label: 'Active' }, { value: 'all', label: 'All' }, ...statuses.map((s) => ({ value: s, label: label(s) }))]}
              onChange={setFilter}
            />
          </div>
          {rows.length === 0 ? (
            <Empty>{all.length ? 'Nobody matches.' : 'No leads yet. Paste your contact list to start.'}</Empty>
          ) : (
            <ul className="lead-list">
              {rows.map((p) => (
                <li key={p.id}>
                  <button className={selected === p.id ? 'lead on' : 'lead'} onClick={() => setSelected(p.id)}>
                    <span className="lead-name">{p.name}</span>
                    <Badge value={p.status} />
                    <span className="muted small">
                      {label(p.channel)}
                      {p.last_contact_at && ` · last contact ${day(p.last_contact_at)}`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="split-detail">
          {selected ? (
            <LeadDetail
              key={selected}
              id={selected}
              fields={fields}
              templates={tpls}
              onChanged={list.reload}
              onDeleted={() => {
                setSelected(null)
                list.reload()
              }}
            />
          ) : (
            <Empty>Select a lead to see the conversation and draft messages.</Empty>
          )}
        </div>
      </div>

      {adding === 'one' && (
        <Modal title="New lead" onClose={() => setAdding(null)}>
          <Form
            fields={fields}
            initial={{ channel: 'facebook', status: 'to_contact', source: 'Personal contact' }}
            submitLabel="Add lead"
            onCancel={() => setAdding(null)}
            onSubmit={(v) =>
              act(async () => {
                const p = await api.post<Prospect>('/api/prospects', { ...v, property_id: propertyId })
                setSelected(p.id)
              }, 'Lead added', () => {
                setAdding(null)
                list.reload()
              })
            }
          />
        </Modal>
      )}

      {adding === 'many' && (
        <Modal title="Paste a contact list" onClose={() => setAdding(null)} wide>
          <p className="muted small">
            One person per line: <code>Name | channel | contact | personal opener</code>. Only the name is
            required. Channel is one of {channels.join(', ')}; if left out, an address with @ is treated as
            email and everything else as Facebook.
          </p>
          <Form
            fields={[
              { key: 'source', label: 'Source for all', placeholder: 'Personal contact' },
              { key: 'lines', label: 'People', type: 'textarea', rows: 12, placeholder: 'Sam Carter | facebook | fb.com/sam.carter | Hope the course in Gagetown went well.' },
            ]}
            initial={{ source: 'Personal contact' }}
            submitLabel="Add all"
            onCancel={() => setAdding(null)}
            onSubmit={(v) => {
              const rows = parseLines(String(v.lines ?? ''), channels).map((p) => ({
                ...p,
                property_id: propertyId,
                source: v.source ?? '',
                status: 'to_contact',
              }))
              if (!rows.length) return
              return act(() => api.post('/api/prospects/bulk', rows), `Added ${rows.length} leads`, () => {
                setAdding(null)
                list.reload()
              })
            }}
          />
        </Modal>
      )}

      {bulkDraft && (
        <Modal title="Draft a message for everyone to contact" onClose={() => setBulkDraft(false)}>
          <BulkDraft
            templates={tpls}
            targets={all.filter((p) => p.status === 'to_contact')}
            onDone={() => {
              setBulkDraft(false)
              list.reload()
            }}
          />
        </Modal>
      )}
    </>
  )
}

function BulkDraft({ templates, targets, onDone }: { templates: Template[]; targets: Prospect[]; onDone: () => void }) {
  const act = useAction()
  const [tid, setTid] = useState<string>('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="form">
      <p>
        Creates one draft per lead marked <b>To contact</b> ({targets.length}). Nothing is sent: you review
        each draft, then copy it into Messenger or send the email.
      </p>
      <p className="muted small">Leads that already have a draft get another one, so run this once per wave.</p>
      <Select value={tid} blank="Choose a template" options={templates.map((t) => ({ value: t.id, label: `${t.name} (${label(t.channel)})` }))} onChange={setTid} />
      <div className="form-actions">
        <button
          disabled={!tid || !targets.length || busy}
          onClick={async () => {
            setBusy(true)
            await act(
              () => Promise.all(targets.map((p) => api.post(`/api/prospects/${p.id}/draft`, { template_id: Number(tid) }))),
              `Drafted ${targets.length} messages`,
              onDone,
            )
            setBusy(false)
          }}
        >
          Create {targets.length} drafts
        </button>
      </div>
    </div>
  )
}

function LeadDetail({
  id,
  fields,
  templates,
  onChanged,
  onDeleted,
}: {
  id: number
  fields: FieldSpec[]
  templates: Template[]
  onChanged: () => void
  onDeleted: () => void
}) {
  const p = useData<Prospect>(`/api/prospects/${id}`)
  const act = useAction()
  const [editing, setEditing] = useState(false)
  const [tid, setTid] = useState('')
  const [reply, setReply] = useState('')
  const [draft, setDraft] = useState('')

  if (p.error) return <div className="error">{p.error}</div>
  if (!p.data) return <p className="muted">Loading…</p>
  const lead = p.data
  const refresh = () => {
    p.reload()
    onChanged()
  }

  return (
    <div className="lead-detail">
      <header className="lead-head">
        <div>
          <h2>{lead.name}</h2>
          <p className="muted small">
            {label(lead.channel)}
            {lead.contact && (
              <>
                {' · '}
                {/^https?:\/\//.test(lead.contact) ? (
                  <a href={lead.contact} target="_blank" rel="noreferrer">{lead.contact}</a>
                ) : (
                  lead.contact
                )}
              </>
            )}
            {lead.source && ` · ${lead.source}`}
          </p>
        </div>
        <div className="actions">
          <Select
            value={lead.status}
            options={fields.find((f) => f.key === 'status')?.options ?? []}
            onChange={(v) => act(() => api.patch(`/api/prospects/${id}`, { status: v }), undefined, refresh)}
          />
          <button className="secondary" onClick={() => setEditing(true)}>Edit</button>
        </div>
      </header>
      {lead.notes && <p className="notes">{lead.notes}</p>}

      <div className="thread">
        {(lead.messages ?? []).length === 0 && <p className="muted small">No messages yet.</p>}
        {(lead.messages ?? []).map((m) => (
          <MessageCard key={m.id} m={m} lead={lead} onChanged={refresh} />
        ))}
      </div>

      <div className="compose">
        <h3>New draft</h3>
        <div className="row">
          <Select value={tid} blank="From template…" options={templates.map((t) => ({ value: t.id, label: t.name }))} onChange={setTid} />
          <button
            className="secondary"
            disabled={!tid}
            onClick={() => act(() => api.post(`/api/prospects/${id}/draft`, { template_id: Number(tid) }), 'Draft created', refresh)}
          >
            Fill template
          </button>
        </div>
        <textarea rows={4} value={draft} placeholder="Or write a draft yourself (or paste one Claude wrote)" onChange={(e) => setDraft(e.target.value)} />
        <div className="row end">
          <button
            className="secondary"
            disabled={!draft.trim()}
            onClick={() =>
              act(() => api.post(`/api/prospects/${id}/messages`, { direction: 'out', body: draft }), 'Draft saved', () => {
                setDraft('')
                refresh()
              })
            }
          >
            Save draft
          </button>
        </div>
        <h3>Log their reply</h3>
        <textarea rows={3} value={reply} placeholder="Paste what they sent you" onChange={(e) => setReply(e.target.value)} />
        <div className="row end">
          <button
            className="secondary"
            disabled={!reply.trim()}
            onClick={() =>
              act(() => api.post(`/api/prospects/${id}/messages`, { direction: 'in', body: reply }), 'Reply logged', () => {
                setReply('')
                refresh()
              })
            }
          >
            Log reply
          </button>
        </div>
      </div>

      {editing && (
        <Modal title="Edit lead" onClose={() => setEditing(false)}>
          <Form
            fields={fields}
            initial={lead}
            submitLabel="Save"
            onCancel={() => setEditing(false)}
            onSubmit={(v) =>
              act(() => api.patch(`/api/prospects/${id}`, v), 'Saved', () => {
                setEditing(false)
                refresh()
              })
            }
            extra={
              <button
                type="button"
                className="danger"
                onClick={() => confirm(`Delete ${lead.name} and their messages?`) && act(() => api.del(`/api/prospects/${id}`), 'Deleted', onDeleted)}
              >
                Delete lead
              </button>
            }
          />
        </Modal>
      )}
    </div>
  )
}

function MessageCard({ m, lead, onChanged }: { m: Message; lead: Prospect; onChanged: () => void }) {
  const act = useAction()
  const [body, setBody] = useState(m.body)
  const [subject, setSubject] = useState(m.subject)
  const dirty = body !== m.body || subject !== m.subject
  const canEmail = m.channel === 'email' && lead.contact.includes('@')

  if (m.status !== 'draft')
    return (
      <div className={`msg ${m.direction}`}>
        <div className="msg-meta">
          {m.direction === 'in' ? `${lead.name} replied` : `You sent (${label(m.channel)})`} · {day(m.sent_at || m.created_at)}
        </div>
        {m.subject && <div className="msg-subject">{m.subject}</div>}
        <div className="msg-body">{m.body}</div>
      </div>
    )

  return (
    <div className="msg draft">
      <div className="msg-meta">Draft · {label(m.channel)}</div>
      {m.channel === 'email' && <input value={subject} placeholder="Subject" onChange={(e) => setSubject(e.target.value)} />}
      <textarea rows={Math.min(22, Math.max(5, body.split('\n').length + Math.ceil(body.length / 95)))} value={body} onChange={(e) => setBody(e.target.value)} />
      <div className="row">
        <button className="ghost" onClick={() => confirm('Discard this draft?') && act(() => api.del(`/api/messages/${m.id}`), 'Draft discarded', onChanged)}>
          Discard
        </button>
        <span className="spacer" />
        {dirty && (
          <button className="secondary" onClick={() => act(() => api.patch(`/api/messages/${m.id}`, { body, subject }), 'Draft saved', onChanged)}>
            Save
          </button>
        )}
        <CopyButton text={body} />
        {canEmail ? (
          <button
            disabled={dirty}
            title={dirty ? 'Save your edits first' : undefined}
            onClick={() =>
              confirm(`Email this to ${lead.contact}?`) &&
              act(() => api.post(`/api/messages/${m.id}/send`), `Emailed ${lead.contact}`, onChanged)
            }
          >
            Send email
          </button>
        ) : (
          <button
            disabled={dirty}
            title={dirty ? 'Save your edits first' : 'Copy it into Messenger or your phone, then mark it sent'}
            onClick={() => act(() => api.post(`/api/messages/${m.id}/send`), 'Marked as sent', onChanged)}
          >
            Mark sent
          </button>
        )}
      </div>
    </div>
  )
}
