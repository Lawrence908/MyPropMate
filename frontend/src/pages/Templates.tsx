import { useState } from 'react'
import type { Template } from '../api'
import { api, label } from '../api'
import type { FieldSpec } from '../components'
import { CopyButton, Empty, Form, Modal, PageHeader } from '../components'
import { useAction, useApp, useData } from '../hooks'

export default function TemplatesPage() {
  const { meta, properties } = useApp()
  const templates = useData<Template[]>('/api/templates')
  const act = useAction()
  const [editing, setEditing] = useState<Partial<Template> | null>(null)

  const placeholders = (meta?.placeholders ?? []).map((p) => `{${p}}`).join('  ')
  const fields: FieldSpec[] = [
    { key: 'name', label: 'Name', placeholder: 'Contacts DM, wave 1' },
    { key: 'channel', label: 'Usual channel', type: 'select', options: meta?.channels ?? [] },
    {
      key: 'property_id',
      label: 'Property',
      type: 'select',
      options: [{ value: '', label: 'Any property' }, ...properties.map((p) => ({ value: p.id, label: p.name }))],
    },
    { key: 'subject', label: 'Email subject', wide: true },
    { key: 'body', label: 'Message', type: 'textarea', rows: 14 },
  ]
  const propName = (id: number | null) => properties.find((p) => p.id === id)?.name ?? 'Any property'

  return (
    <>
      <PageHeader title="Message templates" sub={<>Reusable spiels for leads. Placeholders: <code>{placeholders}</code></>}>
        <button onClick={() => setEditing({ channel: 'facebook', property_id: null })}>New template</button>
      </PageHeader>

      {(templates.data ?? []).length === 0 ? (
        <Empty>No templates yet. Start with your contact DM and an email version.</Empty>
      ) : (
        <div className="cards posts">
          {(templates.data ?? []).map((t) => (
            <article key={t.id} className="card post">
              <header>
                <div>
                  <h3>{t.name}</h3>
                  <p className="muted small">
                    {label(t.channel)} · {propName(t.property_id)}
                  </p>
                </div>
              </header>
              {t.subject && <p className="post-title">{t.subject}</p>}
              <pre className="post-body">{t.body}</pre>
              <footer className="row">
                <button className="ghost" onClick={() => setEditing(t)}>Edit</button>
                <span className="spacer" />
                <CopyButton text={t.body} />
              </footer>
            </article>
          ))}
        </div>
      )}

      {editing && (
        <Modal title={editing.id ? 'Edit template' : 'New template'} onClose={() => setEditing(null)} wide>
          <Form
            fields={fields}
            initial={{ ...editing, property_id: editing.property_id ?? '' }}
            submitLabel={editing.id ? 'Save' : 'Create'}
            onCancel={() => setEditing(null)}
            onSubmit={(v) => {
              const body = { ...v, property_id: v.property_id ? Number(v.property_id) : null }
              return act(
                () => (editing.id ? api.patch(`/api/templates/${editing.id}`, body) : api.post('/api/templates', body)),
                'Saved',
                () => {
                  setEditing(null)
                  templates.reload()
                },
              )
            }}
            extra={
              editing.id && (
                <button
                  type="button"
                  className="danger"
                  onClick={() =>
                    confirm('Delete this template?') &&
                    act(() => api.del(`/api/templates/${editing.id}`), 'Deleted', () => {
                      setEditing(null)
                      templates.reload()
                    })
                  }
                >
                  Delete template
                </button>
              )
            }
          />
        </Modal>
      )}
    </>
  )
}
