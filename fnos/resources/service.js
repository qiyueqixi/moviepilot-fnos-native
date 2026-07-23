const http = require('node:http')
const fs = require('node:fs')
const path = require('node:path')
const express = require('express')
const proxy = require('express-http-proxy')

const app = express()
const backendHost = process.env.MOVIEPILOT_BACKEND_HOST || '127.0.0.1'
const backendPort = Number(process.env.PORT || 3001)
const frontendPort = Number(process.env.NGINX_PORT || 3000)
const gatewayPrefix = process.env.GATEWAY_PREFIX || '/app/moviepilot'
const socketPath = process.env.SOCKET_PATH || ''
const backendUrl = `${backendHost}:${backendPort}`
const assetsPath = path.join(__dirname, 'assets')
const indexPath = path.join(__dirname, 'index.html')
const configPath = process.env.CONFIG_DIR || path.join(__dirname, '..', 'config')
const fnosScale = 0.92
const fnosCompactStyle = `<style id="fnos-compact-ui">
@media (min-width: 900px) {
  html {
    zoom: ${fnosScale};
  }
}
</style>`
const loadingBackgroundNames = [
  'loading-background.webp',
  'loading-background.jpg',
  'loading-background.jpeg',
  'loading-background.png',
]
let isBackendReady = false

function loadingPage (basePath = '/') {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <base href="${basePath}">
  <title>MoviePilot 正在启动</title>
  <style>
    :root { color-scheme: light dark; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; }
    body {
      display: grid;
      place-items: center;
      color: #25262b;
      background: #f3f4f7 url('./fnos-loading-background') center / cover no-repeat;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background: rgba(247, 248, 251, .82);
      backdrop-filter: blur(8px);
    }
    main { position: relative; width: min(420px, calc(100vw - 48px)); text-align: center; }
    .logo { width: 72px; height: 72px; margin-bottom: 22px; }
    h1 { margin: 0; font-size: 22px; font-weight: 650; letter-spacing: 0; }
    p { margin: 10px 0 0; color: #6b6f78; font-size: 14px; line-height: 1.6; }
    .progress { width: 220px; height: 3px; margin: 28px auto 0; overflow: hidden; background: #dfe1e7; border-radius: 2px; }
    .progress::after {
      content: "";
      display: block;
      width: 42%;
      height: 100%;
      background: #8d51f9;
      animation: loading 1.25s ease-in-out infinite;
    }
    #detail { min-height: 23px; }
    #retry { display: none; margin: 18px auto 0; padding: 8px 18px; border: 1px solid #8d51f9; border-radius: 6px; color: #7540d0; background: transparent; cursor: pointer; }
    @keyframes loading { from { transform: translateX(-120%); } to { transform: translateX(340%); } }
    @media (prefers-color-scheme: dark) {
      body { color: #f2f2f4; background-color: #14161a; }
      body::before { background: rgba(18, 20, 24, .84); }
      p { color: #a8abb3; }
      .progress { background: #343740; }
      #retry { color: #b99af7; }
    }
  </style>
</head>
<body>
  <main>
    <img class="logo" src="./logo.svg" alt="MoviePilot">
    <h1>MoviePilot 正在启动</h1>
    <p id="detail">正在初始化运行环境和后台服务</p>
    <div class="progress" aria-label="启动中"></div>
    <button id="retry" type="button">重新检查</button>
  </main>
  <script>
    const startedAt = Date.now()
    const detail = document.querySelector('#detail')
    const retry = document.querySelector('#retry')
    let checking = false

    async function check () {
      if (checking) return
      checking = true
      try {
        const response = await fetch('./fnos-ready?t=' + Date.now(), { cache: 'no-store' })
        const result = await response.json()
        if (result.ready) {
          detail.textContent = '启动完成，正在进入应用'
          location.reload()
          return
        }
      } catch (_) {}
      checking = false
      const seconds = Math.floor((Date.now() - startedAt) / 1000)
      detail.textContent = seconds < 90
        ? '后台服务启动中，已等待 ' + seconds + ' 秒'
        : '启动时间较长，可在应用文件的 logs/moviepilot.log 查看日志'
      if (seconds >= 90) retry.style.display = 'block'
    }

    retry.addEventListener('click', check)
    check()
    setInterval(check, 1000)
  </script>
</body>
</html>`
}

function backendReady () {
  return new Promise(resolve => {
    const request = http.get({ host: backendHost, port: backendPort, path: '/api/v1/system/global?token=moviepilot', timeout: 3000 }, response => {
      response.resume()
      resolve(Boolean(response.statusCode))
    })
    request.on('error', () => resolve(false))
    request.on('timeout', () => { request.destroy(); resolve(false) })
  })
}

function scaleMediaQueries (css) {
  return css.replace(/@media[^\{]+/g, query => query.replace(/(\d+(?:\.\d+)?)px/g, (_match, value) => {
    const scaled = Math.round(Number(value) * fnosScale * 100) / 100
    return `${scaled}px`
  }))
}

function scaleVuetifyBreakpoints (javascript) {
  const scaled = value => Math.round(value * fnosScale * 100) / 100
  return javascript.replace(
    'lg:1280,xl:1920,xxl:2560',
    `lg:${scaled(1280)},xl:${scaled(1920)},xxl:${scaled(2560)}`,
  )
}

function sendIndex (req, res) {
  if (!isBackendReady) {
    const pathname = new URL(req.originalUrl, 'http://localhost').pathname
    const basePath = (pathname.endsWith('/') ? pathname : `${pathname}/`).replaceAll('"', '%22')
    res.set('Cache-Control', 'no-store')
    res.type('html').send(loadingPage(basePath))
    return
  }
  fs.readFile(indexPath, 'utf8', (error, html) => {
    if (error) {
      res.sendStatus(500)
      return
    }
    if (req.query.fnos === '1') {
      html = html
        .replaceAll('./assets/', './fnos-assets/')
        .replace('</head>', `${fnosCompactStyle}</head>`)
    }
    if (req.originalUrl.startsWith(`${gatewayPrefix}/`) || req.originalUrl === gatewayPrefix) {
      html = html
        .replace('<head>', `<head><base href="${gatewayPrefix}/">`)
        .replaceAll('src="/no-auth.js"', 'src="./no-auth.js"')
        .replaceAll("fetch('/logo.svg')", "fetch('./logo.svg')")
    }
    res.set('Cache-Control', 'no-store')
    res.type('html').send(html)
  })
}

app.use((req, res, next) => {
  if (req.path === gatewayPrefix) {
    const query = req.originalUrl.includes('?') ? req.originalUrl.slice(req.originalUrl.indexOf('?')) : ''
    res.redirect(307, `${gatewayPrefix}/${query}`)
    return
  }
  if (req.path.startsWith(`${gatewayPrefix}/`)) {
    req.url = req.url.slice(gatewayPrefix.length) || '/'
  }
  next()
})

app.get('/fnos-ready', async (_req, res) => {
  isBackendReady = await backendReady()
  res.set('Cache-Control', 'no-store').json({ ready: isBackendReady })
})
app.get('/fnos-loading-background', (_req, res) => {
  const background = loadingBackgroundNames
    .map(name => path.join(configPath, name))
    .find(candidate => fs.existsSync(candidate) && fs.statSync(candidate).isFile())
  if (!background) {
    res.sendStatus(404)
    return
  }
  res.set('Cache-Control', 'no-cache').sendFile(background)
})

app.use('/fnos-assets', (req, res, next) => {
  const assetName = path.basename(req.path)
  if (!assetName || req.path !== `/${assetName}`) {
    res.sendStatus(404)
    return
  }
  const extension = path.extname(assetName)
  if (extension !== '.css' && extension !== '.js') {
    next()
    return
  }
  fs.readFile(path.join(assetsPath, assetName), 'utf8', (error, content) => {
    if (error) {
      res.sendStatus(error.code === 'ENOENT' ? 404 : 500)
      return
    }
    const transformed = extension === '.css'
      ? scaleMediaQueries(content)
      : scaleVuetifyBreakpoints(content)
    res.set('Cache-Control', 'no-store')
    res.type(extension).send(transformed)
  })
})
app.use('/fnos-assets', express.static(assetsPath))
app.get(['/', '/index.html'], sendIndex)
app.use(express.static(__dirname, { index: false }))
app.use('/api', proxy(backendUrl, { proxyReqPathResolver: req => `/api${req.url}` }))
app.use('/cookiecloud', proxy(backendUrl, { proxyReqPathResolver: req => `/cookiecloud${req.url}` }))
app.get('*', sendIndex)

function start () {
  const listenTarget = socketPath || frontendPort
  if (socketPath) fs.rmSync(socketPath, { force: true })
  const server = socketPath
    ? app.listen(listenTarget)
    : app.listen(listenTarget, '127.0.0.1')
  const readinessTimer = setInterval(async () => {
    isBackendReady = await backendReady()
  }, 1000)
  backendReady().then(ready => { isBackendReady = ready })
  const stop = () => server.close(() => {
    if (socketPath) fs.rmSync(socketPath, { force: true })
    process.exit(0)
  })
  process.on('SIGTERM', () => { clearInterval(readinessTimer); stop() })
  process.on('SIGINT', () => { clearInterval(readinessTimer); stop() })
}
start()
