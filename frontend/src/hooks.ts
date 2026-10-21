import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from './api'
import type { Meta, Property } from './api'

/** Fetch a path, expose reload. Refetches whenever the path changes. */
export function useData<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!path) return
    let live = true
    api
      .get<T>(path)
      .then((d) => live && (setData(d), setError(null)))
      .catch((e: Error) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [path, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, reload }
}

export type AppState = {
  meta: Meta | null
  properties: Property[]
  reloadProperties: () => void
  /** null means "all properties" */
  propertyId: number | null
  setPropertyId: (id: number | null) => void
  flash: (msg: string, kind?: 'ok' | 'err') => void
}

export const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp outside AppContext')
  return ctx
}

/** Run an API action, flash the outcome, then call onDone. */
export function useAction() {
  const { flash } = useApp()
  return useCallback(
    async (fn: () => Promise<unknown>, ok?: string, onDone?: () => void) => {
      try {
        await fn()
        if (ok) flash(ok)
        onDone?.()
        return true
      } catch (e) {
        flash((e as Error).message, 'err')
        return false
      }
    },
    [flash],
  )
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Clipboard API needs a secure context; plain http over LAN/Tailscale IP is not one.
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  }
}
