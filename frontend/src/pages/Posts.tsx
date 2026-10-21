import { useState } from 'react'
import type { Post } from '../api'
import { api, day, label } from '../api'
import type { FieldSpec } from '../components'
import { Badge, CopyButton, Empty, Form, Modal, NeedProperty, PageHeader, Select } from '../components'
import { useAction, useApp, useData } from '../hooks'

export default function PostsPage() {
  const { propertyId, meta } = useApp()
  const posts = useData<Post[]>(propertyId ? `/api/posts?property_id=${propertyId}` : null)
  const act = useAction()
  const [editing, setEditing] = useState<Partial<Post> | null>(null)
  const [filter, setFilter] = useState('all')

  if (!propertyId) return (<><PageHeader title="Listing posts" /><NeedProperty /></>)

  const fields: FieldSpec[] = [
    { key: 'venue', label: 'Where', placeholder: 'Wainwright Rentals (Facebook group)' },
    { key: 'venue_type', label: 'Type', type: 'select', options: meta?.venue_types ?? [] },
    { key: 'venue_url', label: 'Group or site link', wide: true },
    { key: 'title', label: 'Title', wide: true, placeholder: 'Used where the venue has a title field' },
    { key: 'body', label: 'Post text', type: 'textarea', rows: 12 },
    { key: 'status', label: 'Status', type: 'select', options: meta?.post_statuses ?? [] },
    { key: 'post_url', label: 'Link to the live post', placeholder: 'Paste after posting' },
    { key: 'notes', label: 'Notes', type: 'textarea', rows: 3, placeholder: 'Group rules, repost limits, admin approval…' },
  ]

  const all = posts.data ?? []
  const rows = filter === 'all' ? all : all.filter((p) => p.status === filter)
  const save = (id: number, v: Partial<Post>, ok = 'Saved') => act(() => api.patch(`/api/posts/${id}`, v), ok, posts.reload)

  return (
    <>
      <PageHeader title="Listing posts" sub="One entry per place you advertise. Prepare the text for each, copy it over, then record the live link.">
        <Select value={filter} options={[{ value: 'all', label: 'All' }, ...(meta?.post_statuses ?? []).map((s) => ({ value: s, label: label(s) }))]} onChange={setFilter} />
        <button onClick={() => setEditing({ venue_type: 'fb_group', status: 'draft' })}>Add venue</button>
      </PageHeader>

      {rows.length === 0 ? (
        <Empty>{all.length ? 'Nothing matches this filter.' : 'No posts yet. Add each Facebook group and town site you plan to use.'}</Empty>
      ) : (
        <div className="cards posts">
          {rows.map((p) => (
            <article key={p.id} className="card post">
              <header>
                <div>
                  <h3>{p.venue}</h3>
                  <p className="muted small">
                    {label(p.venue_type)}
                    {p.posted_at && ` · posted ${day(p.posted_at)}`}
                  </p>
                </div>
                <Badge value={p.status} />
              </header>
              {p.title && <p className="post-title">{p.title}</p>}
              <pre className="post-body">{p.body || <span className="muted">No text yet.</span>}</pre>
              {p.notes && <p className="muted small">{p.notes}</p>}
              <footer className="row">
                <button className="ghost" onClick={() => setEditing(p)}>Edit</button>
                <button
                  className="ghost"
                  onClick={() =>
                    act(
                      () => api.post('/api/posts', { ...p, id: undefined, venue: `${p.venue} (copy)`, status: 'draft', posted_at: '', post_url: '' }),
                      'Duplicated',
                      posts.reload,
                    )
                  }
                >
                  Duplicate
                </button>
                <span className="spacer" />
                {p.venue_url && (
                  <a className="button secondary" href={p.venue_url} target="_blank" rel="noreferrer">
                    Open venue
                  </a>
                )}
                {p.post_url && (
                  <a className="button secondary" href={p.post_url} target="_blank" rel="noreferrer">
                    Live post
                  </a>
                )}
                <CopyButton text={p.title ? `${p.title}\n\n${p.body}` : p.body} />
                {p.status !== 'posted' && p.status !== 'closed' ? (
                  <button onClick={() => save(p.id, { status: 'posted', posted_at: new Date().toISOString().slice(0, 19) }, 'Marked as posted')}>
                    Mark posted
                  </button>
                ) : p.status === 'posted' ? (
                  <button className="secondary" onClick={() => save(p.id, { status: 'closed' }, 'Closed')}>
                    Close
                  </button>
                ) : null}
              </footer>
            </article>
          ))}
        </div>
      )}

      {editing && (
        <Modal title={editing.id ? 'Edit post' : 'New venue'} onClose={() => setEditing(null)} wide>
          <Form
            fields={fields}
            initial={editing}
            submitLabel={editing.id ? 'Save' : 'Add'}
            onCancel={() => setEditing(null)}
            onSubmit={(v) =>
              act(
                () => (editing.id ? api.patch(`/api/posts/${editing.id}`, v) : api.post('/api/posts', { ...v, property_id: propertyId })),
                'Saved',
                () => {
                  setEditing(null)
                  posts.reload()
                },
              )
            }
            extra={
              editing.id && (
                <button
                  type="button"
                  className="danger"
                  onClick={() =>
                    confirm('Delete this post?') &&
                    act(() => api.del(`/api/posts/${editing.id}`), 'Deleted', () => {
                      setEditing(null)
                      posts.reload()
                    })
                  }
                >
                  Delete post
                </button>
              )
            }
          />
        </Modal>
      )}
    </>
  )
}
