(() => {
  const encode = value => btoa(JSON.stringify(value))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replaceAll('=', '')
  const now = Math.floor(Date.now() / 1000)
  const fallbackToken = [
    encode({ alg: 'none', typ: 'JWT' }),
    encode({
      sub: '0',
      username: 'admin',
      super_user: true,
      level: 0,
      purpose: 'authentication',
      iat: now,
      exp: now + 315360000,
    }),
    'fnos',
  ].join('.')

  let session = null
  try {
    const request = new XMLHttpRequest()
    request.open('POST', './api/v1/login/access-token', false)
    request.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded')
    request.send('username=admin&password=fnos')
    if (request.status >= 200 && request.status < 300) {
      session = JSON.parse(request.responseText)
    }
  } catch (_) {}

  const level = Number(session?.level) || 0
  const token = session?.access_token || fallbackToken

  localStorage.setItem('auth', JSON.stringify({
    token,
    remember: true,
    originalPath: null,
  }))
  localStorage.setItem('user', JSON.stringify({
    superUser: true,
    userID: 0,
    userName: 'admin',
    avatar: session?.avatar || '',
    level,
    permissions: session?.permissions || {},
    wizard: Boolean(session?.wizard),
  }))
})()
