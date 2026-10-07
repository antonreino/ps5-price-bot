import gzip
import json
import time
import urllib.request
import urllib.error
from email.utils import parsedate_to_datetime


class FetchError(Exception):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def retry_seconds(value):
    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return 0


def fetch(url, timeout=18):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'PS5PriceBot/1.0 (personal price monitor)',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/rss+xml',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise FetchError('Respuesta demasiado grande')
            if response.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
            return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
    except urllib.error.HTTPError as exc:
        raise FetchError(f'HTTP {exc.code}', retry_seconds(exc.headers.get('Retry-After'))) from None
    except (OSError, urllib.error.URLError) as exc:
        raise FetchError(f'Error de red: {type(exc).__name__}') from None


class Telegram:
    def __init__(self, token):
        self.token = token

    def call(self, method, data=None, timeout=30):
        req = urllib.request.Request(f'https://api.telegram.org/bot{self.token}/{method}',
                                     data=json.dumps(data or {}).encode(),
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read())
            except (ValueError, OSError):
                result = {}
            wait = result.get('parameters', {}).get('retry_after', 0)
            # No registrar URL ni exception original: contienen el token.
            raise FetchError(f'Telegram HTTP {exc.code}', wait) from None
        except (OSError, urllib.error.URLError, ValueError):
            raise FetchError('Telegram: fallo de conexión/respuesta') from None
        if not result.get('ok'):
            raise FetchError('Telegram: operación rechazada')
        return result['result']

    def send(self, chat, text):
        return self.call('sendMessage', {'chat_id': chat, 'text': text, 'parse_mode': 'HTML',
                                       'link_preview_options': {'is_disabled': True}})
