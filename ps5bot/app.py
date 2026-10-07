import argparse
from concurrent.futures import ThreadPoolExecutor
from html import escape
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlsplit
from .network import fetch, FetchError, Telegram
from .parsers import parse_page, ParseError
from .store import Store
from .models import FAMILIES

ROOT = Path(__file__).resolve().parent.parent
LOG = logging.getLogger('ps5bot')
DOMAINS = {
    'amazon': 'amazon.es', 'fnac': 'fnac.es', 'mediamarkt': 'mediamarkt.es',
    'pccomponentes': 'pccomponentes.com', 'idealo': 'idealo.es', 'chollometro': 'chollometro.com',
}


def env_file():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


def load_config(path):
    cfg = json.loads(Path(path).read_text())
    if not isinstance(cfg.get('interval_seconds'), (int, float)) or cfg['interval_seconds'] < 30:
        raise ValueError('interval_seconds debe ser al menos 30')
    if not 1 <= cfg.get('timeout_seconds', 18) <= 25:
        raise ValueError('timeout_seconds debe estar entre 1 y 25')
    names = set()
    for s in cfg['sources']:
        s.setdefault('family', 'ps5')
        if s['family'] not in FAMILIES:
            raise ValueError('Familia desconocida')
        if s['name'] in names:
            raise ValueError('Los nombres de fuentes deben ser únicos')
        names.add(s['name'])
        domain = DOMAINS[s['parser']]
        if s['kind'] not in ('retailer', 'comparison', 'deal'):
            raise ValueError('Tipo de fuente desconocido')
        if not s.get('urls'):
            raise ValueError('Cada fuente necesita al menos una URL')
        for url in s['urls']:
            p = urlsplit(url)
            if p.scheme != 'https' or not p.hostname or not (p.hostname == domain or p.hostname.endswith('.'+domain)):
                raise ValueError(f'URL no válida para {s["name"]}')
    return cfg


def source_interval(source, cfg):
    """Cadencia individual; evita castigar proveedores sensibles a consultas frecuentes."""
    if isinstance(source.get('interval_seconds'), (int, float)) and source['interval_seconds'] >= 30:
        return source['interval_seconds']
    parser = source.get('parser')
    if parser == 'amazon':
        return 900  # 15 minutos
    if parser == 'pccomponentes':
        return 300  # 5 minutos
    return cfg['interval_seconds']


def collect(source, cfg, diagnostics=None):
    offers = {}
    # Una fuente solo se publica si todas sus páginas configuradas se leen correctamente.
    for url in source['urls']:
        html = fetch(url, cfg.get('timeout_seconds', 18))
        report = {} if diagnostics is not None else None
        for offer in parse_page(html, url, source, cfg.get('model_overrides'), cfg.get('include_used', False), report):
            offers[offer.key] = offer
        if diagnostics is not None:
            diagnostics.append(report)
    return list(offers.values())


def command_reply(message, username, allowed, store, cfg):
    chat = str(message.get('chat', {}).get('id', ''))
    if chat not in allowed:
        return None
    text = message.get('text', '').strip().split()
    if not text:
        return None
    command, _, suffix = text[0].partition('@')
    if suffix and suffix.lower() != username.lower():
        return None
    family = 'switch2' if command in ('/switch2', '/zelda', '/estado_switch2', '/chollos_switch2') else 'ps5'
    selected = [s for s in cfg['sources'] if s.get('family', 'ps5') == family]
    enabled = {s['name'] for s in selected if s.get('enabled', True)}
    if command in ('/ps5', '/switch2', '/zelda'):
        return store.summary(cfg.get('stale_after_seconds', 180), enabled=enabled, family=family)
    if command in ('/estado', '/estado_ps5', '/estado_switch2'):
        return store.status(cfg['sources'] if command == '/estado' else selected)
    if command in ('/chollos', '/chollos_switch2'):
        return store.deals(enabled=enabled, family=family)
    if command == '/logs':
        return store.logs()
    if command in ('/start', '/help', '/ayuda'):
        return ('/ps5 — mejor precio reciente de cada modelo\n'
                '/switch2 — consola Zelda 40.º aniversario (también /zelda)\n'
                '/estado — estado actual y próxima revisión\n'
                '/estado_ps5 · /estado_switch2 — estado por consola\n'
                '/logs — últimos errores y recuperaciones\n'
                '/chollos · /chollos_switch2 — anuncios por consola\n'
                'Telegram solo avisa de productos/ofertas y cambios de precio o stock. PS5 Pro excluida.')
    return None


def commands(api, store, cfg, allowed, username, stop):
    offset = int(store.get_meta('telegram_offset'))
    while not stop.is_set():
        try:
            updates = api.call('getUpdates', {'offset': offset, 'timeout': 20, 'allowed_updates': ['message']}, timeout=25)
            for update in updates:
                message = update.get('message', {})
                reply = command_reply(message, username, allowed, store, cfg)
                if reply:
                    store.queue(reply, message['chat']['id'])
                offset = update['update_id'] + 1
                store.set_meta('telegram_offset', offset)
        except FetchError as exc:
            LOG.warning('%s; si HTTP 409, hay otro proceso/webhook usando este bot.', exc)
            stop.wait(max(5, exc.retry_after))
        except Exception as exc:
            LOG.error('Error en comandos: %s', type(exc).__name__)
            stop.wait(5)


def notifications(api, store, stop):
    while not stop.is_set():
        row = store.pending()
        if row is None:
            stop.wait(0.5)
            continue
        try:
            api.send(row['chat'], row['body'])
            store.sent(row['id'])
            stop.wait(1.1)
        except FetchError as exc:
            delay = max(exc.retry_after, min(1800, 5 * 2 ** min(row['attempts'], 9)))
            store.retry(row['id'], delay)
            LOG.warning('%s; notificación retenida en cola.', exc)
            stop.wait(max(1, exc.retry_after))


def run(cfg, store, stop):
    sources = [s for s in cfg['sources'] if s.get('enabled', True)]
    jobs, failures = {}, {}
    started = time.monotonic()
    due = {s['name']: started + max(0, float(s.get('initial_delay_seconds', 0))) for s in sources}
    interval = cfg['interval_seconds']
    with ThreadPoolExecutor(max_workers=max(1, len(sources))) as pool:
        while not stop.is_set():
            for s in sources:
                name = s['name']
                job = jobs.get(name)
                if job and job.done():
                    base_interval = source_interval(s, cfg)
                    error, wait, offers = None, base_interval, []
                    try:
                        offers = job.result()
                        failures[name] = 0
                    except (FetchError, ParseError) as exc:
                        error = str(exc)
                        failures[name] = failures.get(name, 0) + 1
                        wait = max(getattr(exc, 'retry_after', 0), min(3600, base_interval * 2 ** min(failures[name], 6)))
                        if 'HTTP 403' in error or 'CAPTCHA' in error:
                            wait = max(wait, 1800)
                        elif 'HTTP 429' in error:
                            wait = max(wait, 600)
                    except Exception as exc:
                        error = 'Error del adaptador: ' + type(exc).__name__
                        wait = 300
                    # Cadencia desde el inicio de la consulta, sin solapar ni acumular ejecuciones.
                    due[name] = time.monotonic() + wait if error else max(time.monotonic(), due[name] + wait)
                    next_wall = time.time() + max(0, due[name] - time.monotonic())
                    store.source_result(name, offers, error, next_wall)
                    if error:
                        LOG.warning('%s: %s; pausa %.0f s', name, error, wait)
                    else:
                        LOG.info('%s: %d fichas', name, len(offers))
                    del jobs[name]
                if name not in jobs and time.monotonic() >= due.get(name, 0):
                    due[name] = time.monotonic()
                    jobs[name] = pool.submit(collect, s, cfg)
            stop.wait(0.25)


def main():
    parser = argparse.ArgumentParser(description='Bot de precios PS5 y Switch 2 Zelda')
    parser.add_argument('--config', default=str(ROOT / 'config.json'))
    parser.add_argument('--check', action='store_true', help='Una lectura por fuente, sin Telegram ni modificar la base de datos')
    parser.add_argument('--source', help='Filtra --check por el nombre exacto, por ejemplo Amazon')
    parser.add_argument('--diagnose', action='store_true', help='Con --check: títulos y precios descartados; no imprime credenciales ni HTML')
    args = parser.parse_args()
    env_file()
    cfg = load_config(args.config)
    if args.check:
        def check(source):
            reports = [] if args.diagnose else None
            try:
                offers = collect(source, cfg, reports)
                return source['name'], offers, None, reports
            except (FetchError, ParseError) as exc:
                return source['name'], [], str(exc), reports
        sources = [s for s in cfg['sources'] if s.get('enabled', True) and (not args.source or s['name'] == args.source)]
        if not sources:
            parser.error('No existe una fuente activa con ese nombre')
        failed = False
        with ThreadPoolExecutor(max_workers=max(1, len(sources))) as pool:
            for name, offers, error, reports in pool.map(check, sources):
                print(f'{name}: ' + (error if error else (f'OK, {len(offers)} fichas' if offers else 'SIN COINCIDENCIAS VÁLIDAS')), flush=True)
                failed |= bool(error)
                for o in offers:
                    print(f'  {o.model} | {o.price/100:.2f} EUR | {o.availability} | {o.title}\n  {o.url}')
                if reports:
                    print(json.dumps(reports, ensure_ascii=False, indent=2))
        return 2 if failed else 0
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chats = tuple(x.strip() for x in os.environ.get('TELEGRAM_CHAT_IDS', '').split(',') if x.strip())
    if not token or not chats:
        parser.error('Faltan credenciales. Ejecuta python scripts/configure.py')
    if any(not x.lstrip('-').isdigit() for x in chats):
        parser.error('TELEGRAM_CHAT_IDS debe contener identificadores numéricos')
    data = ROOT / 'data'
    data.mkdir(exist_ok=True, mode=0o700)
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[RotatingFileHandler(logs / 'bot.log', maxBytes=2_000_000, backupCount=3), logging.StreamHandler()])
    # Impide dos instancias locales y las carreras de SQLite/getUpdates.
    import fcntl
    lock = (data / 'bot.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Ya hay una instancia ejecutándose en esta carpeta')
    api = Telegram(token)
    try:
        me = api.call('getMe')
        if api.call('getWebhookInfo').get('url'):
            parser.error('Este bot tiene un webhook activo. Usa un bot nuevo de BotFather para evitar conflictos.')
    except FetchError as exc:
        parser.error(str(exc))
    store = Store(data / 'prices.sqlite3', chats)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    threads = [threading.Thread(target=commands, args=(api, store, cfg, chats, me['username'], stop), daemon=True),
               threading.Thread(target=notifications, args=(api, store, stop), daemon=True)]
    for t in threads:
        t.start()
    try:
        run(cfg, store, stop)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=27)
        lock.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
