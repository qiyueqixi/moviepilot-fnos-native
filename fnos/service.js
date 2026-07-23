const http = require('node:http')
const path = require('node:path')
const express = require('express')
const proxy = require('express-http-proxy')

const app = express()
const backendHost = process.env.MOVIEPILOT_BACKEND_HOST || '127.0.0.1'
const backendPort = Number(process.env.PORT || 3001)
const frontendPort = Number(process.env.NGINX_PORT || 3000)
const backendUrl = `${backendHost}:${backendPort}`

function backendReady () {
  return new Promise(resolve => {
    const request = http.get({ host: backendHost, port: backendPort, path: '/api/v1/system/global?token=moviepilot', timeout: 3000 }, response => {
      response.resume()
      resolve(response.statusCode === 200)
    })
    request.on('error', () => resolve(false))
    request.on('timeout', () => { request.destroy(); resolve(false) })
  })
}

app.use(express.static(__dirname))
app.use('/api', proxy(backendUrl, { proxyReqPathResolver: req => `/api${req.url}` }))
app.use('/cookiecloud', proxy(backendUrl, { proxyReqPathResolver: req => `/cookiecloud${req.url}` }))
app.get('*', (_req, res) => res.sendFile(path.join(__dirname, 'index.html')))

async function start () {
  for (let attempt = 0; attempt < 30 && !(await backendReady()); attempt++) await new Promise(resolve => setTimeout(resolve, 1000))
  if (!(await backendReady())) process.exit(1)
  const server = app.listen(frontendPort, '0.0.0.0')
  const stop = () => server.close(() => process.exit(0))
  process.on('SIGTERM', stop)
  process.on('SIGINT', stop)
}
start().catch(() => process.exit(1))
