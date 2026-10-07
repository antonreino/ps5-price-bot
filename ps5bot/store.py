from dataclasses import asdict
from datetime import datetime
from html import escape
import hashlib
import json
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo
from .models import LABELS, FAMILIES, euro


class Store:
    def __init__(self, path, chats=()):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.chats = tuple(chats)
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS offers (
                key TEXT PRIMARY KEY, source TEXT, payload TEXT, price INTEGER,
                model TEXT, seen REAL, active INTEGER);
            CREATE TABLE IF NOT EXISTS sources (
                name TEXT PRIMARY KEY, initialized INTEGER DEFAULT 0,
                ok INTEGER DEFAULT 0, detail TEXT DEFAULT '', checked REAL DEFAULT 0,
                success REAL DEFAULT 0, next_check REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat TEXT, body TEXT,
                attempts INTEGER DEFAULT 0, due REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS published_notifications (
                fingerprint TEXT PRIMARY KEY, body TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS source_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, level TEXT NOT NULL,
                detail TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS source_events_created_idx ON source_events(created DESC);
        ''')
        self.db.commit()

    def queue(self, body, chat=None):
        chunks, current = [], ''
        for line in body.splitlines(keepends=True):
            if len(current) + len(line) > 3500 and current:
                chunks.append(current)
                current = ''
            current += line
        if current:
            chunks.append(current)
        with self.lock, self.db:
            for target in ((str(chat),) if chat is not None else self.chats):
                for chunk in chunks:
                    self.db.execute('INSERT INTO outbox(chat,body) VALUES (?,?)', (target, chunk))

    def source_result(self, name, offers, error=None, next_check=0, now=None):
        now = time.time() if now is None else now
        with self.lock, self.db:
            self.db.execute('INSERT OR IGNORE INTO sources(name) VALUES (?)', (name,))
            state = self.db.execute('SELECT * FROM sources WHERE name=?', (name,)).fetchone()
            def notify_once(body):
                # Persistente entre reinicios: el mismo aviso exacto no vuelve a publicarse.
                fingerprint = hashlib.sha256(body.encode('utf-8')).hexdigest()
                cur = self.db.execute(
                    'INSERT OR IGNORE INTO published_notifications(fingerprint,body,created) VALUES (?,?,?)',
                    (fingerprint, body, now))
                if not cur.rowcount:
                    return False
                for chat in self.chats:
                    self.db.execute('INSERT INTO outbox(chat,body) VALUES (?,?)', (chat, body))
                return True

            def source_event(level, detail):
                # Evita llenar /logs con el mismo 429/403 en cada intento.
                last = self.db.execute(
                    'SELECT level,detail FROM source_events WHERE name=? ORDER BY id DESC LIMIT 1',
                    (name,)).fetchone()
                if last is None or last['level'] != level or last['detail'] != detail:
                    self.db.execute(
                        'INSERT INTO source_events(name,level,detail,created) VALUES (?,?,?,?)',
                        (name, level, detail, now))

            if error:
                source_event('error', error)
                self.db.execute('UPDATE sources SET ok=0,detail=?,checked=?,next_check=? WHERE name=?',
                                (error, now, next_check, name))
                return
            if state['checked'] and not state['ok']:
                source_event('recovery', f'Vuelve a responder: {len(offers)} fichas objetivo identificadas')
            self.db.execute('UPDATE offers SET active=0 WHERE source=?', (name,))
            # Deduplicación por ficha y vendedor, nunca por el mínimo global.
            for offer in {o.key: o for o in offers}.values():
                old = self.db.execute('SELECT * FROM offers WHERE key=?', (offer.key,)).fetchone()
                body = None
                if state['initialized'] and offer.availability != 'out_of_stock':
                    prefix = 'Anuncio Chollometro · sin confirmar' if offer.kind == 'deal' else name
                    if old and old['price'] != offer.price:
                        delta = offer.price - old['price']
                        direction = '📉 Bajada' if delta < 0 else '📈 Subida'
                        pct = abs(delta) * 100 / old['price']
                        body = (f'{direction} · {escape(LABELS[offer.model])}\n'
                                f'{escape(prefix)}\n{euro(old["price"])} → <b>{euro(offer.price)}</b> '
                                f'({"+" if delta > 0 else "−"}{euro(abs(delta))}; {pct:.1f} %)')
                    elif old is None:
                        body = f'🆕 Nueva ficha · {escape(LABELS[offer.model])}\n{escape(prefix)} · <b>{euro(offer.price)}</b>'
                    elif json.loads(old['payload'])['availability'] == 'out_of_stock' and offer.availability in ('in_stock', 'preorder'):
                        label = 'Reserva disponible' if offer.availability == 'preorder' else 'Vuelve el stock'
                        body = f'📦 {label} · {escape(LABELS[offer.model])}\n{escape(prefix)} · <b>{euro(offer.price)}</b>'
                    if body:
                        body += f'\n{escape(offer.title)}'
                        if offer.seller:
                            body += f'\nVendedor: {escape(offer.seller)}'
                        if offer.kind == 'comparison':
                            body += '\nPrecio «desde» de comparador; confirmar condiciones y stock.'
                        elif offer.availability == 'unknown':
                            body += '\nStock pendiente de confirmar.'
                        elif offer.availability == 'preorder':
                            body += '\nPreventa/reserva; confirma la fecha de entrega.'
                        body += '\nEnvío: ' + (euro(offer.shipping) if offer.shipping is not None else 'por confirmar')
                        body += f'\n<a href="{escape(offer.url, quote=True)}">Ver oferta</a>'
                        notify_once(body)
                self.db.execute('INSERT OR REPLACE INTO offers VALUES (?,?,?,?,?,?,1)',
                                (offer.key, name, json.dumps(asdict(offer), ensure_ascii=False),
                                 offer.price, offer.model, now))
            self.db.execute('UPDATE sources SET initialized=1,ok=1,detail=?,checked=?,success=?,next_check=? WHERE name=?',
                            (f'{len(offers)} fichas objetivo identificadas' if offers else 'Sin coincidencias válidas; no hay un precio monitorizado', now, now, next_check, name))

    def summary(self, stale=180, now=None, enabled=None, family='ps5'):
        now = time.time() if now is None else now
        with self.lock:
            rows = self.db.execute('SELECT * FROM offers WHERE active=1 AND seen>=?', (now-stale,)).fetchall()
            states = self.db.execute('SELECT * FROM sources').fetchall()
        good_sources = {s['name'] for s in states if s['ok'] and (enabled is None or s['name'] in enabled)}
        offers = [json.loads(r['payload']) | {'seen': r['seen']} for r in rows if r['source'] in good_sources]
        offers = [o for o in offers if o['availability'] != 'out_of_stock']
        lines = []
        for model in FAMILIES[family]:
            label = LABELS[model]
            candidates = [o for o in offers if o['model'] == model]
            if not candidates:
                lines.append(f'{label}: sin precio reciente disponible')
                continue
            best = min(candidates, key=lambda o: (o['price'], o['url']))
            qualifier = 'desde ' if best['kind'] == 'comparison' else ('oferta ' if best['kind'] == 'deal' else '')
            link_label = ('Comparar ofertas' if best['kind'] == 'comparison' else
                          ('Ver oferta' if best['kind'] == 'deal' else
                           ('Reservar' if best['availability'] == 'preorder' else 'Comprar')))
            line = (f'{label}: <b>{qualifier}{euro(best["price"])}</b> · '
                    f'<a href="{escape(best["url"], quote=True)}">{link_label}</a> ({escape(best["source"])})')
            if best['seller']:
                line += f' · {escape(best["seller"])}'
            line += f'\n  {escape(best["title"][:170])}'
            line += '\n  ' + {'in_stock': 'Stock indicado disponible', 'preorder': 'Preventa/reserva; confirmar entrega'}.get(best['availability'], 'Stock por confirmar')
            line += '; envío ' + (euro(best['shipping']) if best['shipping'] is not None else 'por confirmar')
            line += ' · ' + datetime.fromtimestamp(best['seen'], ZoneInfo('Europe/Madrid')).strftime('%H:%M:%S')
            lines.append(line)
        lines.append('\nMínimos entre fichas y ofertas detectadas; precio del artículo, sin sumar envío. En Chollometro confirma vigencia, cupón, envío y stock. Packs identificados por su título.')
        lines.append('Anuncios de Chollometro: ' + ('/chollos_switch2' if family == 'switch2' else '/chollos'))
        return '\n'.join(lines)

    def deals(self, now=None, enabled=None, family='ps5'):
        now = time.time() if now is None else now
        with self.lock:
            rows = self.db.execute('SELECT payload,seen FROM offers WHERE active=1 AND seen>=? ORDER BY seen DESC LIMIT 200', (now-180,)).fetchall()
            good = {r['name'] for r in self.db.execute('SELECT name FROM sources WHERE ok=1')}
        deals = [json.loads(r['payload']) for r in rows]
        deals = [o for o in deals if o['kind'] == 'deal' and o['model'] in FAMILIES[family] and o['source'] in good and (enabled is None or o['source'] in enabled)][:8]
        if not deals:
            return 'No hay anuncios de Chollometro leídos recientemente. Consulta /estado.'
        return 'Anuncios; confirma vigencia, cupón, envío y stock en la tienda:\n\n' + '\n\n'.join(
            f'{escape(o["title"][:160])}: <b>{euro(o["price"])}</b>\n<a href="{escape(o["url"], quote=True)}">Ver anuncio</a>' for o in deals)

    def status(self, configured):
        with self.lock:
            states = {r['name']: r for r in self.db.execute('SELECT * FROM sources')}
            pending = self.db.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]
        lines = ['Estado de las fuentes (hora de Madrid):']
        for source in configured:
            if not source.get('enabled', True):
                lines.append(f'⏸ {escape(source["name"])}: desactivada')
                continue
            s = states.get(source['name'])
            if s is None or not s['checked']:
                lines.append(f'⏳ {escape(source["name"])}: esperando primera lectura')
                continue
            stamp = datetime.fromtimestamp(s['checked'], ZoneInfo('Europe/Madrid')).strftime('%d/%m %H:%M:%S')
            next_stamp = datetime.fromtimestamp(s['next_check'], ZoneInfo('Europe/Madrid')).strftime('%H:%M:%S')
            empty = s['detail'].startswith(('Sin coincidencias', '0 fichas'))
            icon = '⚠️' if not s['ok'] else ('🟡' if empty else '✅')
            lines.append(f'{icon} {escape(source["name"])}: {escape(s["detail"])}\n  Última consulta: {stamp}; próxima: {next_stamp}')
        lines.append(f'Notificaciones en cola: {pending}')
        return '\n'.join(lines)

    def logs(self, limit=25):
        limit = max(1, min(int(limit), 100))
        with self.lock:
            rows = self.db.execute(
                'SELECT name,level,detail,created FROM source_events ORDER BY id DESC LIMIT ?',
                (limit,)).fetchall()
        if not rows:
            return 'No hay errores ni recuperaciones registrados.'
        lines = ['Últimos eventos técnicos (hora de Madrid):']
        for row in rows:
            stamp = datetime.fromtimestamp(row['created'], ZoneInfo('Europe/Madrid')).strftime('%d/%m %H:%M:%S')
            icon = '⚠️' if row['level'] == 'error' else '✅'
            lines.append(f'{icon} {stamp} · {escape(row["name"])}: {escape(row["detail"])}')
        return '\n'.join(lines)

    def get_meta(self, key, default='0'):
        with self.lock:
            row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            return row[0] if row else default

    def set_meta(self, key, value):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, str(value)))

    def pending(self):
        with self.lock:
            return self.db.execute('SELECT * FROM outbox WHERE due<=? ORDER BY id LIMIT 1', (time.time(),)).fetchone()

    def sent(self, ident):
        with self.lock, self.db:
            self.db.execute('DELETE FROM outbox WHERE id=?', (ident,))

    def retry(self, ident, delay):
        with self.lock, self.db:
            self.db.execute('UPDATE outbox SET attempts=attempts+1,due=? WHERE id=?', (time.time()+delay, ident))
