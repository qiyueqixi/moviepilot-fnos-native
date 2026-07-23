(async () => {
  if (localStorage.getItem('auth')) return
  const form = new FormData()
  form.append('username', 'admin')
  form.append('password', '')
  const response = await fetch('/api/v1/login/access-token', { method: 'POST', body: form })
  if (!response.ok) return
  const token = await response.json()
  localStorage.setItem('auth', JSON.stringify({ token: token.access_token, remember: true, originalPath: null }))
  location.reload()
})().catch(() => {})
