// Thin typed wrapper over the FastAPI backend. Same origin in production,
// proxied by Vite in dev, so every path is relative.

export type Property = {
  id: number
  name: string
  address: string
  city: string
  province: string
  status: string
  notes: string
}

export type Counts = {
  tasks: Record<string, number>
  prospects: Record<string, number>
  posts: Record<string, number>
  tenants: number
}

export type Overview = {
  properties: (Property & { counts: Counts })[]
  payments: { pending: number; failed: number; sent: number }
}

export type Tenant = {
  id: number
  display_name: string
  monthly_rent: number
  parking_fee: number
  phone: string
  email: string
  last_invoice_no: number
  property_id: number | null
}

export type Payment = {
  reference_number: string
  sender_name: string
  amount: number
  period: string
  payment_date: string
  invoice_no: number | null
  receipt_path: string | null
  emailed: number
  created_at: string
  tenant_name: string | null
  property_id: number | null
}

export type Task = {
  id: number
  property_id: number
  code: string
  title: string
  category: string
  grp: string
  status: string
  due_date: string
  assignee: string
  notes: string
}

export type Message = {
  id: number
  prospect_id: number
  direction: 'out' | 'in'
  channel: string
  subject: string
  body: string
  status: 'draft' | 'sent' | 'received'
  created_at: string
  sent_at: string
}

export type Prospect = {
  id: number
  property_id: number
  name: string
  channel: string
  contact: string
  source: string
  status: string
  personal_note: string
  notes: string
  last_contact_at: string
  updated_at: string
  messages?: Message[]
}

export type Post = {
  id: number
  property_id: number
  venue: string
  venue_type: string
  venue_url: string
  title: string
  body: string
  status: string
  posted_at: string
  post_url: string
  notes: string
}

export type Template = {
  id: number
  property_id: number | null
  name: string
  channel: string
  subject: string
  body: string
}

export type Meta = {
  property_statuses: string[]
  task_statuses: string[]
  task_categories: string[]
  prospect_statuses: string[]
  channels: string[]
  post_statuses: string[]
  venue_types: string[]
  placeholders: string[]
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* not JSON */
    }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: (path: string) => request<{ status: string }>('DELETE', path),
}

export const label = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

export const money = (n: number) =>
  n.toLocaleString('en-CA', { style: 'currency', currency: 'CAD' })

export const day = (iso: string) => (iso ? iso.slice(0, 10) : '')
