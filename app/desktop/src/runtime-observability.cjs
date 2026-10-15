const SECRET_NAMES = 'password|passwd|passphrase|cookie|set-cookie|authorization|token|csrf|xsrf|secret|api[_-]?key|sessionid'
const SECRET_KEY = new RegExp(SECRET_NAMES, 'i')
const SECRET_PREFIX = new RegExp(`\\b(${SECRET_NAMES})((?:\\\\*["'])?\\s*[:=]\\s*)`, 'i')
const RAW_KEY = /^(html|raw_html|raw_response|raw_body|page_source)$/i

function redactText(value, depth = 0) {
  if (depth > 12) return '[DEPTH_LIMIT]'
  return redactEmbeddedJson(String(value), depth)
}

function redactPlainText(text) {
  const match = SECRET_PREFIX.exec(text)
  // 标记前缀不证明尾部安全；边界不可信时停止输出后续片段。
  const value = match ? text.slice(0, match.index + match[0].length) + '[REDACTED]' : text
  const sanitized = value
    .replace(/\bBearer\s+[^\s,;"']+/gi, 'Bearer [REDACTED]')
    .replace(/\bsk-[A-Za-z0-9_-]{8,}/g, '[REDACTED]')
    .replace(/(https?:\/\/[^\s?#"']+)\?[^\s"']+/gi, '$1?[REDACTED]')
  return { text: sanitized, truncated: Boolean(match) }
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
      if (typeof parsed === 'string' && !'{["'.includes(parsed.trimStart()[0])
        && (text.slice(0, index).trim() || text.slice(end).trim())) continue
      const plain = redactPlainText(text.slice(cursor, index))
      parts.push(plain.text)
      if (plain.truncated) return parts.join('')
      // JSON 值完成脱敏后直接输出，文本正则不能跨越其结构边界。
      parts.push(JSON.stringify(redactValue(parsed, depth + 1)))
      cursor = end
      index = end - 1
    } catch {
      // 不是有效 JSON 时交给下方保守秘密扫描，不保留未闭合秘密的尾部。
    }
  }
  parts.push(redactPlainText(text.slice(cursor)).text)
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
