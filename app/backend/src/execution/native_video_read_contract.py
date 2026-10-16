"""只允许原生视频浮层自身发起的精确读取；不是主动接口或全局白名单。"""

from urllib.parse import urlsplit


NATIVE_VIDEO_READ_BODIES = {
    '/api/picToVideo/backMusicList.json': ('application/json', '{}'),
    '/api/picToVideo/getCountInfo.json': ('application/json', '{}'),
    '/api/midou/valueService/balanceView.json': ('application/x-www-form-urlencoded', 'types=17'),
}


def is_native_video_read(request, page):
    parts = urlsplit(request.url)
    expected = NATIVE_VIDEO_READ_BODIES.get(parts.path)
    if expected is None:
        return False
    content_type, body = expected
    return (request.method == 'POST' and parts.scheme == 'https' and parts.netloc == 'www.dianxiaomi.com'
        and not parts.query and not parts.fragment and request.resource_type in {'xhr', 'fetch'}
        and request.frame is page.main_frame and request.redirected_from is None
        and request.headers.get('content-type', '').split(';')[0].strip().lower() == content_type
        and request.post_data == body)
