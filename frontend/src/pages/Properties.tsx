import { useState } from 'react'
import type { Property } from '../api'
import { api } from '../api'
import type { FieldSpec } from '../components'
import { Badge, Empty, Form, Modal, PageHeader } from '../components'
import { useAction, useApp } from '../hooks'

export default function PropertiesPage() {
  const { properties, reloadProperties, meta, setPropertyId } = useApp()
  const act = useAction()
  const [editing, setEditing] = useState<Partial<Property> | null>(null)

  const fields: FieldSpec[] = [
    { key: 'name', label: 'Name', placeholder: 'Wainwright house' },
    { key: 'status', label: 'Status', type: 'select', options: meta?.property_statuses ?? [] },
    { key: 'address', label: 'Address', wide: true },
    { key: 'city', label: 'City' },
    { key: 'province', label: 'Province' },
    { key: 'notes', label: 'Notes', type: 'textarea', rows: 6, placeholder: 'Access, utilities, key dates, anything you would otherwise have to remember' },
  ]

  return (
    <>
      <PageHeader title="Properties" sub="Each house you rent, are selling, or are buying.">
        <button onClick={() => setEditing({ status: 'rented', province: 'AB' })}>Add property</button>
      </PageHeader>

      {properties.length === 0 ? (
        <Empty>No properties yet.</Empty>
      ) : (
        <div className="cards">
          {properties.map((p) => (
            <article key={p.id} className="card">
              <header>
                <div>
                  <h3>{p.name}</h3>
                  <p className="muted">{[p.address, p.city, p.province].filter(Boolean).join(', ')}</p>
                </div>
                <Badge value={p.status} />
              </header>
              {p.notes && <p className="notes">{p.notes}</p>}
              <footer className="row">
                <button className="ghost" onClick={() => setEditing(p)}>Edit</button>
                <span className="spacer" />
                <button className="secondary" onClick={() => setPropertyId(p.id)}>Work on this one</button>
              </footer>
            </article>
          ))}
        </div>
      )}

      {editing && (
        <Modal title={editing.id ? 'Edit property' : 'New property'} onClose={() => setEditing(null)}>
          <Form
            fields={fields}
            initial={editing}
            submitLabel={editing.id ? 'Save' : 'Add property'}
            onCancel={() => setEditing(null)}
            onSubmit={(v) =>
              act(
                async () => {
                  if (editing.id) await api.patch(`/api/properties/${editing.id}`, v)
                  else setPropertyId((await api.post<Property>('/api/properties', v)).id)
                },
                'Saved',
                () => {
                  setEditing(null)
                  reloadProperties()
                },
              )
            }
            extra={
              editing.id && (
                <button
                  type="button"
                  className="danger"
                  onClick={() =>
                    confirm(`Delete ${editing.name}? Its tasks, leads, posts and templates are deleted too. Tenants and payments are kept.`) &&
                    act(() => api.del(`/api/properties/${editing.id}`), 'Deleted', () => {
                      setEditing(null)
                      reloadProperties()
                    })
                  }
                >
                  Delete property
                </button>
              )
            }
          />
        </Modal>
      )}
    </>
  )
}
