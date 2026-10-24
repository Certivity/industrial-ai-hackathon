import { useCallback, useSyncExternalStore } from 'react'

export type Route = 'requirements' | 'assess'

const routes: Route[] = ['requirements', 'assess']

function subscribe(onChange: () => void) {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

const read = (): Route => {
  const hash = window.location.hash.replace(/^#\/?/, '')
  return routes.find((r) => r === hash) ?? 'requirements'
}

/** Minimal hash router: two top-level pages, back button and reload keep the tab. */
export function useRoute(): [Route, (route: Route) => void] {
  const route = useSyncExternalStore(subscribe, read)
  const navigate = useCallback((next: Route) => {
    window.location.hash = `/${next}`
  }, [])
  return [route, navigate]
}
