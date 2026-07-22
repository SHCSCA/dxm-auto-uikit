export type SourceProductUrlValidation = {
  ok: boolean
  message: string
}

export function validateSourceProductUrl(value: string | null | undefined): SourceProductUrlValidation {
  const raw = String(value ?? '').trim()
  if (!raw) {
    return { ok: false, message: '从上方选择一条带来源 URL 的商品，或粘贴真实来源商品的完整链接。' }
  }
  if (/\s|[\u0000-\u001f\u007f]/.test(raw) || /%(?![0-9a-f]{2})/i.test(raw)) {
    return unsupportedSourceUrl()
  }

  try {
    const url = new URL(raw)
    const hostname = url.hostname.toLowerCase().replace(/\.$/, '')
    const authority = raw.match(/^[a-z][a-z0-9+.-]*:\/\/([^/?#]+)/i)?.[1] ?? ''
    const hasExplicitPort = /:\d+$/.test(authority)
    const supportedProtocol = url.protocol === 'http:' || url.protocol === 'https:'
    const safeAuthority = Boolean(hostname) && !url.username && !url.password && !url.port && !hasExplicitPort
    if (!supportedProtocol || !safeAuthority) {
      return unsupportedSourceUrl()
    }

    const hostMatches = (domain: string) => hostname === domain || hostname.endsWith(`.${domain}`)
    const supported1688 = hostMatches('1688.com') && /^\/offer\/[0-9]+\.html$/i.test(url.pathname)
    const goodsIds = url.searchParams.getAll('goods_id')
    const supportedPinduoduo = hostMatches('yangkeduo.com')
      && /^\/goods2?\.html$/i.test(url.pathname)
      && goodsIds.length === 1
      && /^[0-9]+$/.test(goodsIds[0])
    const supportedAliExpress = hostMatches('aliexpress.com') && /^\/item\/[0-9]+\.html$/i.test(url.pathname)

    if (!supported1688 && !supportedPinduoduo && !supportedAliExpress) {
      return unsupportedSourceUrl()
    }
    return { ok: true, message: '精确来源商品 URL 已就绪。' }
  } catch {
    return { ok: false, message: '来源商品 URL 格式不完整，请粘贴包含 https://、站点域名和商品 ID 的完整链接。' }
  }
}

export function isSupportedSourceProductUrl(value: string | null | undefined) {
  return validateSourceProductUrl(value).ok
}

function unsupportedSourceUrl(): SourceProductUrlValidation {
  return {
    ok: false,
    message: '仅支持 1688、拼多多或 AliExpress 的精确商品详情链接；不要填写搜索页、店小秘页面或本机地址。',
  }
}
