import { useState } from 'react'
import type { ReactNode } from 'react'
import { label } from './api'
import { copyText, useApp } from './hooks'

export function Badge({ value }: { value: string }) {
  return <span className={`badge badge-${value}`}>{label(value)}</span>
}

export function Select({
  value,
  options,
  onChange,
  blank,
}: {
  value: string | number | null
  options: (string | { value: string | number; label: string })[]
  onChange: (v: string) => void
  blank?: string
}) {
  return (
    <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
      {blank !== undefined && <option value="">{blank}</option>}
      {options.map((o) =>
        typeof o === 'string' ? (
          <option key={o} value={o}>
            {label(o)}
          </option>
        ) : (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ),
      )}
    </select>
  )
}

export function Field({ label: l, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={wide ? 'field wide' : 'field'}>
      <span>{l}</span>
      {children}
    </label>
  )
}

export type FieldSpec = {
  key: string
  label: string
  type?: 'text' | 'textarea' | 'select' | 'date' | 'number'
  options?: (string | { value: string | number; label: string })[]
  wide?: boolean
  rows?: number
  placeholder?: string
}

/** A small form driven by a field list. Used for every create/edit dialog. */
export function Form({
  fields,
  initial,
  submitLabel,
  onSubmit,
  onCancel,
  extra,
}: {
  fields: FieldSpec[]
  initial: Record<string, unknown>
  submitLabel: string
  onSubmit: (values: Record<string, unknown>) => Promise<boolean> | void
  onCancel?: () => void
  extra?: ReactNode
}) {
  const [values, setValues] = useState<Record<string, unknown>>(initial)
  const [busy, setBusy] = useState(false)
  const set = (k: string, v: unknown) => setValues((s) => ({ ...s, [k]: v }))

  return (
    <form
      className="form"
      onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        await onSubmit(values)
        setBusy(false)
      }}
    >
      <div className="form-grid">
        {fields.map((f) => {
          const v = (values[f.key] ?? '') as string
          let input: ReactNode
          if (f.type === 'textarea')
            input = (
              <textarea rows={f.rows ?? 6} value={v} placeholder={f.placeholder}
                onChange={(e) => set(f.key, e.target.value)} />
            )
          else if (f.type === 'select')
            input = <Select value={v} options={f.options ?? []} onChange={(x) => set(f.key, x)} />
          else
            input = (
              <input type={f.type ?? 'text'} value={v} placeholder={f.placeholder}
                onChange={(e) => set(f.key, f.type === 'number' ? Number(e.target.value) : e.target.value)} />
            )
          return (
            <Field key={f.key} label={f.label} wide={f.wide || f.type === 'textarea'}>
              {input}
            </Field>
          )
        })}
      </div>
      {extra}
      <div className="form-actions">
        {onCancel && (
          <button type="button" className="ghost" onClick={onCancel}>
            Cancel
          </button>
        )}
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : submitLabel}
        </button>
      </div>
    </form>
  )
}

export function Modal({ title, onClose, children, wide }: {
  title: string; onClose: () => void; children: ReactNode; wide?: boolean
}) {
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={wide ? 'modal wide' : 'modal'} role="dialog" aria-label={title}>
        <header>
          <h2>{title}</h2>
          <button className="ghost icon" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        {children}
      </div>
    </div>
  )
}

export function CopyButton({ text, children = 'Copy' }: { text: string; children?: ReactNode }) {
  const { flash } = useApp()
  return (
    <button
      type="button"
      className="secondary"
      onClick={async () => {
        const ok = await copyText(text)
        flash(ok ? 'Copied to clipboard' : 'Copy failed, select the text manually', ok ? 'ok' : 'err')
      }}
    >
      {children}
    </button>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function PageHeader({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      <div className="actions">{children}</div>
    </div>
  )
}

/** Banner shown on pages that need a property but "All properties" is selected. */
export function NeedProperty() {
  return <Empty>Pick a property in the sidebar to see and add items here.</Empty>
}
