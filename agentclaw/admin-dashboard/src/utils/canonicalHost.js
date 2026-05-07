const INVALID_BIND_HOSTS = new Set(['0.0.0.0', '::', '[::]'])

export function getCanonicalDashboardUrl(locationLike) {
  if (!locationLike || !INVALID_BIND_HOSTS.has(locationLike.hostname)) return ''

  const protocol = locationLike.protocol || 'http:'
  const port = locationLike.port ? `:${locationLike.port}` : ''
  const pathname = locationLike.pathname || '/'
  const search = locationLike.search || ''
  const hash = locationLike.hash || ''
  return `${protocol}//127.0.0.1${port}${pathname}${search}${hash}`
}

export function redirectInvalidBindHost(locationLike = window.location) {
  const nextUrl = getCanonicalDashboardUrl(locationLike)
  if (!nextUrl) return false
  locationLike.replace(nextUrl)
  return true
}
