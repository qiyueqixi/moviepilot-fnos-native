const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')

const source = fs.readFileSync(path.resolve(__dirname, '../../../fnos/resources/no-auth.js'), 'utf8')

function setup () {
  class XHR {
    open (...args) { this.args = args; this.headers = {} }
    setRequestHeader (name, value) { this.headers[name] = value }
    send () { this.status = 200; this.responseText = '{"level":2,"permissions":{}}' }
  }
  const storage = new Map()
  const calls = []
  const context = {
    URL, Request, Headers, XMLHttpRequest: XHR, btoa,
    document: { baseURI: 'https://nas.example/app/moviepilot/' },
    localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    window: { fetch: (...args) => { calls.push(args); return Promise.resolve() } },
  }
  vm.runInNewContext(source, context)
  return { ...context, storage, calls }
}

test('native XHR keeps NAS cookies and drops MoviePilot bearer headers', () => {
  const { XMLHttpRequest: XHR, storage } = setup()
  const request = new XHR()
  request.open('GET', './api/v1/site/auth')
  request.withCredentials = true
  request.setRequestHeader('Authorization', 'Bearer moviepilot')
  request.setRequestHeader('Content-Type', 'application/json')
  assert.equal(request.headers.Authorization, undefined)
  assert.equal(request.headers['Content-Type'], 'application/json')
  assert.equal(request.withCredentials, true)
  assert.equal(JSON.parse(storage.get('user')).level, 2)
  request.open('GET', 'https://tracker.example/api/v1/site/auth')
  request.setRequestHeader('Authorization', 'Bearer tracker')
  assert.equal(request.headers.Authorization, 'Bearer tracker')
  request.open('GET', '/api/other-fnos-app')
  request.setRequestHeader('authorization', 'Bearer nas')
  assert.equal(request.headers.authorization, 'Bearer nas')
})

test('native fetch removes bearer headers without changing method, body or credentials', async () => {
  const { window, calls } = setup()
  const init = {
    method: 'POST', body: '{"site":"hhclub"}', credentials: 'include',
    headers: { Authorization: 'Bearer moviepilot', 'Content-Type': 'application/json' },
  }
  await window.fetch('./api/v1/site/auth', init)
  assert.equal(calls[0][1].headers.has('Authorization'), false)
  assert.equal(calls[0][1].headers.get('Content-Type'), 'application/json')
  assert.equal(calls[0][1].method, init.method)
  assert.equal(calls[0][1].body, init.body)
  assert.equal(calls[0][1].credentials, 'include')
  assert.equal(init.headers.Authorization, 'Bearer moviepilot')
  const request = new Request('https://nas.example/app/moviepilot/api/v1/system/global', {
    headers: { authorization: 'Bearer moviepilot', 'X-Test': 'retained' },
  })
  await window.fetch(request)
  assert.equal(calls[1][1].headers.has('Authorization'), false)
  assert.equal(calls[1][1].headers.get('X-Test'), 'retained')
  await window.fetch('https://tracker.example/api/v1/', init)
  assert.equal(calls[2][1], init)
})
