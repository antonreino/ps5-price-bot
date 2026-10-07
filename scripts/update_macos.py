#!/usr/bin/env python3
"""Actualiza una instalación existente sin copiar ni modificar .env, data o logs."""
import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PACKAGE = Path(__file__).resolve().parent.parent
LABEL = f'com.{Path.home().name}.ps5-price-bot'


def merge_config(current, defaults):
    result = copy.deepcopy(current)
    for key, value in defaults.items():
        if key not in ('sources', 'model_overrides'):
            result.setdefault(key, copy.deepcopy(value))
    result['config_version'] = defaults.get('config_version', 3)
    result.setdefault('model_overrides', {})
    for key, value in defaults.get('model_overrides', {}).items():
        result['model_overrides'].setdefault(key, value)
    existing = {s['name']: s for s in result['sources']}
    default_by_name = {s['name']: s for s in defaults['sources']}
    for source in result['sources']:
        source.setdefault('family', 'ps5')
        # Incorpora nuevas opciones técnicas sin pisar personalizaciones existentes.
        template = default_by_name.get(source['name'], {})
        for key, value in template.items():
            if key not in ('urls', 'enabled'):
                source.setdefault(key, copy.deepcopy(value))
    for source in defaults['sources']:
        if source['name'] not in existing:
            new = copy.deepcopy(source)
            # Mantener desactivado un proveedor si el usuario ya lo desactivó en PS5.
            base = next((s for s in current['sources'] if s.get('parser') == new.get('parser') and s.get('family', 'ps5') == 'ps5'), None)
            if base is not None:
                new['enabled'] = base.get('enabled', True)
            result['sources'].append(new)
    return result


def package_files(root):
    for name in ('README.md', 'VALIDACION.md', 'ACTUALIZAR.md', 'requirements.txt'):
        yield root / name
    for folder in ('ps5bot', 'scripts'):
        for file in sorted((root / folder).rglob('*')):
            if file.is_file() and file.suffix in ('.py', '.sh') and '__pycache__' not in file.parts:
                yield file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=Path, help='Carpeta del bot ya instalado')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Este actualizador es para macOS')
    target = args.target.expanduser().resolve()
    if target == PACKAGE:
        parser.error('Descomprime la actualización en otra carpeta, sin sustituir previamente la instalación')
    if not (target / '.env').is_file() or not (target / 'config.json').is_file():
        parser.error('No se encuentra una instalación configurada en esa carpeta')
    python = target / '.venv/bin/python'
    if not python.is_file():
        parser.error('No se encuentra el entorno .venv de la instalación')
    defaults = json.loads((PACKAGE / 'config.json').read_text())
    merged = merge_config(json.loads((target / 'config.json').read_text()), defaults)
    files = list(package_files(PACKAGE))
    for file in files:
        if not file.is_file():
            parser.error('Paquete incompleto: ' + file.name)
        if file.suffix == '.py':
            compile(file.read_text(), str(file), 'exec')
        (target / file.relative_to(PACKAGE)).resolve().relative_to(target)
    (target / 'config.json').resolve().relative_to(target)
    subprocess.run([str(python), '-c', 'import sys, bs4; assert sys.version_info >= (3,10)'], check=True)
    domain = f'gui/{os.getuid()}'
    plist = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    was_running = subprocess.run(['launchctl', 'print', domain+'/'+LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if was_running:
        subprocess.run(['launchctl', 'bootout', domain+'/'+LABEL], check=True)
    lock = None
    saved, created = [], []
    backup = target / 'backups' / ('update-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    try:
        import fcntl
        (target / 'data').mkdir(exist_ok=True)
        lock = (target / 'data/bot.lock').open('a')
        for attempt in range(120):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if attempt == 119:
                    raise RuntimeError('Sigue ejecutándose otra instancia; ciérrala antes de actualizar')
                time.sleep(0.25)
        backup.mkdir(parents=True)
        for rel in [file.relative_to(PACKAGE) for file in files] + [Path('config.json')]:
            dest = target / rel
            if dest.exists():
                old = backup / rel
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, old)
                saved.append(rel)
            else:
                created.append(rel)
        for file in files:
            dest = target / file.relative_to(PACKAGE)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dest)
        tmp = target / 'config.json.update-tmp'
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2)+'\n')
        os.replace(tmp, target / 'config.json')
        subprocess.run([str(python), '-c', 'from ps5bot.app import load_config; load_config("config.json")'], cwd=target, check=True)
        lock.close()
        lock = None
        subprocess.run([str(python), str(target / 'scripts/launch_agent.py'), 'install'], check=True)
    except BaseException:
        for rel in saved:
            shutil.copy2(backup / rel, target / rel)
        for rel in created:
            (target / rel).unlink(missing_ok=True)
        if lock:
            lock.close()
        if was_running and plist.exists():
            subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=False)
        print('Actualización interrumpida; se han restaurado los archivos anteriores.', file=sys.stderr)
        raise
    print('Actualizado. Se conserva el token, el chat, el historial y tu configuración de PS5.')
    print('Copia de los archivos sustituidos:', backup)
    print('En Telegram: /switch2 y /estado_switch2. PS5: /ps5.')


if __name__ == '__main__':
    raise SystemExit(main())
