import { useState } from 'react'
import type { Task } from '../api'
import { api, label } from '../api'
import type { FieldSpec } from '../components'
import { Empty, Form, Modal, NeedProperty, PageHeader, Select } from '../components'
import { useAction, useApp, useData } from '../hooks'

/** Parse pasted lines of "CODE | Title | Notes" (tabs work too) into tasks. */
function parseLines(text: string) {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const parts = l.split(/\s*[|\t]\s*/)
      if (parts.length === 1) return { code: '', title: parts[0], notes: '' }
      return { code: parts[0], title: parts[1] ?? '', notes: parts.slice(2).join(' ') }
    })
    .filter((t) => t.title)
}

export default function TasksPage() {
  const { propertyId, meta } = useApp()
  const tasks = useData<Task[]>(propertyId ? `/api/tasks?property_id=${propertyId}` : null)
  const act = useAction()
  const [editing, setEditing] = useState<Partial<Task> | null>(null)
  const [importing, setImporting] = useState(false)
  const [statusFilter, setStatusFilter] = useState('open')

  if (!propertyId) return (<><PageHeader title="Tasks" /><NeedProperty /></>)

  const fields: FieldSpec[] = [
    { key: 'code', label: 'Code', placeholder: 'A1' },
    { key: 'title', label: 'Title', wide: true },
    { key: 'grp', label: 'Group', placeholder: 'Priority A' },
    { key: 'category', label: 'Category', type: 'select', options: meta?.task_categories ?? [] },
    { key: 'status', label: 'Status', type: 'select', options: meta?.task_statuses ?? [] },
    { key: 'due_date', label: 'Due', type: 'date' },
    { key: 'assignee', label: 'Assigned to', placeholder: 'Vendor or person' },
    { key: 'notes', label: 'Notes', type: 'textarea', rows: 5 },
  ]

  const all = tasks.data ?? []
  const visible = all.filter((t) =>
    statusFilter === 'all' ? true : statusFilter === 'open' ? !['done', 'skipped'].includes(t.status) : t.status === statusFilter,
  )
  const groups = new Map<string, Task[]>()
  for (const t of visible) {
    const g = t.grp || 'Ungrouped'
    groups.set(g, [...(groups.get(g) ?? []), t])
  }

  return (
    <>
      <PageHeader title="Tasks" sub="Maintenance, vendor work, admin and sale prep for this property.">
        <Select
          value={statusFilter}
          options={[{ value: 'open', label: 'Open' }, { value: 'all', label: 'All' }, ...(meta?.task_statuses ?? []).map((s) => ({ value: s, label: label(s) }))]}
          onChange={setStatusFilter}
        />
        <button className="secondary" onClick={() => setImporting(true)}>Import list</button>
        <button onClick={() => setEditing({ category: 'maintenance', status: 'todo' })}>Add task</button>
      </PageHeader>

      {visible.length === 0 ? (
        <Empty>{all.length ? 'Nothing matches this filter.' : 'No tasks yet. Add one, or import a scope of work.'}</Empty>
      ) : (
        [...groups.entries()].map(([g, list]) => (
          <section key={g} className="group">
            <h2 className="section-title">
              {g} <span className="muted">{list.filter((t) => t.status === 'done').length}/{list.length} done</span>
            </h2>
            <ul className="task-list">
              {list.map((t) => (
                <li key={t.id} className={`task status-${t.status}`}>
                  <input
                    type="checkbox"
                    aria-label="Done"
                    checked={t.status === 'done'}
                    onChange={(e) =>
                      act(() => api.patch(`/api/tasks/${t.id}`, { status: e.target.checked ? 'done' : 'todo' }), undefined, tasks.reload)
                    }
                  />
                  <button className="task-main" onClick={() => setEditing(t)}>
                    {t.code && <span className="code">{t.code}</span>}
                    <span className="task-title">{t.title}</span>
                    {t.notes && <span className="task-notes">{t.notes}</span>}
                  </button>
                  <div className="task-meta">
                    {t.assignee && <span className="muted small">{t.assignee}</span>}
                    {t.due_date && <span className="muted small">due {t.due_date}</span>}
                    <span className="muted small">{label(t.category)}</span>
                    <Select
                      value={t.status}
                      options={meta?.task_statuses ?? []}
                      onChange={(v) => act(() => api.patch(`/api/tasks/${t.id}`, { status: v }), undefined, tasks.reload)}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}

      {editing && (
        <Modal title={editing.id ? 'Edit task' : 'New task'} onClose={() => setEditing(null)}>
          <Form
            fields={fields}
            initial={editing}
            submitLabel={editing.id ? 'Save' : 'Add task'}
            onCancel={() => setEditing(null)}
            onSubmit={(v) =>
              act(
                () => (editing.id ? api.patch(`/api/tasks/${editing.id}`, v) : api.post('/api/tasks', { ...v, property_id: propertyId })),
                'Saved',
                () => {
                  setEditing(null)
                  tasks.reload()
                },
              )
            }
            extra={
              editing.id && (
                <button
                  type="button"
                  className="danger"
                  onClick={() =>
                    confirm('Delete this task?') &&
                    act(() => api.del(`/api/tasks/${editing.id}`), 'Deleted', () => {
                      setEditing(null)
                      tasks.reload()
                    })
                  }
                >
                  Delete task
                </button>
              )
            }
          />
        </Modal>
      )}

      {importing && (
        <Modal title="Import tasks" onClose={() => setImporting(false)} wide>
          <p className="muted small">
            One task per line: <code>CODE | Title | Notes</code>. Code and notes are optional; tabs work
            as separators too, so you can paste table rows from a doc.
          </p>
          <Form
            fields={[
              { key: 'grp', label: 'Group', placeholder: 'Priority A' },
              { key: 'category', label: 'Category', type: 'select', options: meta?.task_categories ?? [] },
              { key: 'due_date', label: 'Due', type: 'date' },
              { key: 'assignee', label: 'Assigned to' },
              { key: 'lines', label: 'Tasks', type: 'textarea', rows: 12, placeholder: 'A1 | Regrade soil around the perimeter | 6 inches of fall over 6 feet' },
            ]}
            initial={{ category: 'maintenance' }}
            submitLabel="Import"
            onCancel={() => setImporting(false)}
            onSubmit={(v) => {
              const rows = parseLines(String(v.lines ?? '')).map((t) => ({
                ...t,
                property_id: propertyId,
                grp: v.grp ?? '',
                category: v.category,
                due_date: v.due_date ?? '',
                assignee: v.assignee ?? '',
              }))
              if (!rows.length) return
              return act(() => api.post('/api/tasks/bulk', rows), `Imported ${rows.length} tasks`, () => {
                setImporting(false)
                tasks.reload()
              })
            }}
          />
        </Modal>
      )}
    </>
  )
}
