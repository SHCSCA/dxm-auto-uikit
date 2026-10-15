const SECRET_KEY = /password|passwd|passphrase|cookie|authorization|token|csrf|xsrf|secret|api[_-]?key|sessionid/i
const RAW_KEY = /^(html|raw_html|raw_response|raw_body|page_source)$/i

function redactText(value, depth = 0) {
  if (depth > 12) return '[DEPTH_LIMIT]'
  let structured = redactEmbeddedJson(String(value), depth)
  const prefix = /\b(password|passwd|cookie|set-cookie|authorization|token|csrf|xsrf|secret|api[_-]?key|sessionid)((?:\\*["'])?\s*[:=]\s*)/gi
  for (const match of structured.matchAll(prefix)) {
    const end = match.index + match[0].length
    if (!structured.slice(end).replace(/^[\\"']+/, '').startsWith('[REDACTED]')) {
      structured = structured.slice(0, end) + '[REDACTED]'
      break
    }
  }
  return structured
    .replace(/\b(cookie|set-cookie|authorization)(\s*[:=]\s*)[^\r\n]+/gi,
      (_match, key, separator) => `${key}${separator}[REDACTED]`)
    .replace(/\b(password|passwd|cookie|authorization|token|csrf|xsrf|secret|api[_-]?key|sessionid)(["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/gis,
      (_match, key, separator, quoted) => `${key}${separator}${quoted[0]}[REDACTED]${quoted[0]}`)
    .replace(/\bBearer\s+[^\s,;"']+/gi, 'Bearer [REDACTED]')
    .replace(/\bsk-[A-Za-z0-9_-]{8,}/g, '[REDACTED]')
    .replace(/(https?:\/\/[^\s?#"']+)\?[^\s"']+/gi, '$1?[REDACTED]')
}

function jsonValueEnd(text, start) {
  const stack = []
  let quoted = false
  let escaped = false
  for (let index = start; index < text.length; index += 1) {
    const char = text[index]
    if (quoted) {
      if (escaped) escaped = false
      else if (char === '\\') escaped = true
      else if (char === '"') {
        quoted = false
        if (stack.length === 0) return index + 1
      }
      continue
    }
    if (char === '"') quoted = true
    else if (char === '{' || char === '[') stack.push(char)
    else if (char === '}' || char === ']') {
      if (stack.pop() !== (char === '}' ? '{' : '[')) return null
      if (stack.length === 0) return index + 1
    }
  }
  return null
}

function redactEmbeddedJson(text, depth) {
  const parts = []
  let cursor = 0
  for (let index = 0; index < text.length; index += 1) {
    if (!'{["'.includes(text[index])) continue
    const end = jsonValueEnd(text, index)
    if (end === null) continue
    try {
      const parsed = JSON.parse(text.slice(index, end))
      parts.push(text.slice(cursor, index), JSON.stringify(redactValue(parsed, depth + 1)))
      cursor = end
      index = end - 1
    } catch {
      // 不是有效 JSON 时交给下方保守秘密扫描，不保留未闭合秘密的尾部。
    }
  }
  parts.push(text.slice(cursor))
  return parts.join('')
}

function redactValue(value, depth = 0) {
  if (depth > 12) return '[DEPTH_LIMIT]'
  if (Array.isArray(value)) return value.map((item) => redactValue(item, depth + 1))
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key,
      SECRET_KEY.test(key) ? '[REDACTED]' : RAW_KEY.test(key) ? '[OMITTED]' : redactValue(item, depth + 1),
    ]))
  }
  if (value === null || typeof value === 'boolean' || typeof value === 'number') return value
  return redactText(value, depth + 1)
}

function serializeDesktopLog(event, { level = 'INFO', fields = {} } = {}) {
  return JSON.stringify({
    schema: 'dxm.log.v1',
    timestamp: new Date().toISOString(),
    level: level.toUpperCase(),
    component: 'desktop',
    event: redactText(event),
    fields: redactValue(fields),
  })
}

function exceptionFields(reason) {
  return {
    exception_type: reason instanceof Error ? reason.name : typeof reason,
    exception_message: reason instanceof Error ? reason.message : String(reason),
    traceback: reason instanceof Error ? reason.stack : undefined,
  }
}

module.exports = { redactText, redactValue, serializeDesktopLog, exceptionFields }
