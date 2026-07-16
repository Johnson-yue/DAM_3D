const API = ''

export async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, options)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  return res
}

export function statusClass(status) {
  if (status === 'ready') return 'ready'
  if (status === 'failed') return 'failed'
  if (status === 'processing' || status === 'copied') return 'processing'
  return ''
}
