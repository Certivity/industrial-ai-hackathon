import { useCallback, useSyncExternalStore } from 'react'

export type Route = 'home' | 'requirements' | 'assess'

const routes: Route[] = ['home', 'requirements', 'assess']

function subscribe(onChange: () => void) {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

const read = (): Route => {
  const hash = window.location.hash.replace(/^#\/?/, '')
  return routes.find((r) => r === hash) ?? 'home'
}

/** Minimal hash router: three top-level pages, back button and reload keep the page. */
export function useRoute(): [Route, (route: Route) => void] {
  const route = useSyncExternalStore(subscribe, read)
  const navigate = useCallback((next: Route) => {
    window.location.hash = `/${next}`
    window.scrollTo({ top: 0 })
  }, [])
  return [route, navigate]
}
