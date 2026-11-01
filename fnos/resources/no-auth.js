(() => {
  // fnOS authenticates gateway requests before they reach MoviePilot. Its
  // gateway must receive the NAS session cookie, without MoviePilot's bearer
  // token taking precedence. The native backend already enables no-login.
  const apiBase = new URL('./api/', document.baseURI)
  const isNativeApi = value => {
    try {
      const url = new URL(value, document.baseURI)
      return url.origin === apiBase.origin && url.pathname.startsWith(apiBase.pathname)
    } catch (_) {
      return false
    }
  }
  const nativeRequests = new WeakSet()
  const xhrOpen = XMLHttpRequest.prototype.open
  const xhrSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader
  XMLHttpRequest.prototype.open = function (method, url, ...args) {
    nativeRequests.delete(this)
    if (isNativeApi(url)) nativeRequests.add(this)
    return xhrOpen.call(this, method, url, ...args)
  }
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    if (nativeRequests.has(this) && name.toLowerCase() === 'authorization') return
    return xhrSetRequestHeader.call(this, name, value)
  }
  const originalFetch = window.fetch
  window.fetch = function (input, init) {
    const url = input instanceof Request ? input.url : input
    if (!isNativeApi(url)) return originalFetch.call(this, input, init)
    const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined))
    headers.delete('Authorization')
    return originalFetch.call(this, input, { ...init, headers })
  }

  const encode = value => btoa(JSON.stringify(value))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replaceAll('=', '')
  const readStored = key => {
    try {
      return JSON.parse(localStorage.getItem(key) || 'null')
    } catch (_) {
      return null
    }
  }
  const now = Math.floor(Date.now() / 1000)
  const previousUser = readStored('user')

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

  const sessionLevel = session ? Number(session.level) : NaN
  const previousLevel = Number(previousUser?.level)
  const level = Number.isFinite(sessionLevel)
    ? sessionLevel
    : (Number.isFinite(previousLevel) ? previousLevel : 0)
  const token = [
    encode({ alg: 'none', typ: 'JWT' }),
    encode({
      sub: '0',
      username: 'admin',
      super_user: true,
      level,
      purpose: 'authentication',
      iat: now,
      exp: now + 315360000,
    }),
    'fnos',
  ].join('.')

  localStorage.setItem('auth', JSON.stringify({
    token,
    remember: true,
    originalPath: null,
  }))
  localStorage.setItem('user', JSON.stringify({
    superUser: true,
    userID: 0,
    userName: 'admin',
    avatar: session?.avatar || previousUser?.avatar || '',
    level,
    permissions: session?.permissions || previousUser?.permissions || {},
    wizard: session ? Boolean(session.wizard) : Boolean(previousUser?.wizard),
  }))
})()
