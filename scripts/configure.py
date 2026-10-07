#!/usr/bin/env python3
"""Asocia un bot NUEVO con tu chat privado, sin mostrar ni transmitir el token a terceros."""
import getpass
import os
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ps5bot.network import Telegram, FetchError


def main():
    if (ROOT / '.env').exists():
        print('Ya existe .env. Edítalo para cambiar credenciales; no se sobrescribirá.')
        return 0
    print('Crea un bot NUEVO en https://t.me/BotFather con /newbot.')
    token = getpass.getpass('Pega su token (no se muestra): ').strip()
    if not token or '\n' in token or ':' not in token:
        print('Token no válido.')
        return 1
    api = Telegram(token)
    try:
        me = api.call('getMe')
        if api.call('getWebhookInfo').get('url'):
            print('Ese bot ya tiene webhook. Crea otro bot para este proyecto.')
            return 1
        code = secrets.token_hex(4)
        print(f'Abre https://t.me/{me["username"]} y envíale exactamente: /start {code}')
        print('Esperando hasta 5 minutos. No ejecutes otro proceso con este token.')
        offset = 0
        until = time.monotonic() + 300
        while time.monotonic() < until:
            for update in api.call('getUpdates', {'offset': offset, 'timeout': 20, 'allowed_updates': ['message']}, timeout=25):
                offset = update['update_id'] + 1
                msg = update.get('message', {})
                if msg.get('chat', {}).get('type') != 'private' or msg.get('text', '').strip() != '/start ' + code:
                    continue
                chat = msg['chat']['id']
                fd = os.open(ROOT / '.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as f:
                    f.write(f'TELEGRAM_BOT_TOKEN={token}\nTELEGRAM_CHAT_IDS={chat}\n')
                print(f'Configurado para tu chat {chat}. El token ha quedado guardado en .env.')
                return 0
    except FetchError as exc:
        print(str(exc))
        print('Si es HTTP 409, otro proceso está leyendo el mismo bot. Utiliza un bot nuevo.')
        return 1
    print('Se agotó el tiempo. Ejecuta de nuevo este asistente.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
