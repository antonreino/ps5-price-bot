#!/usr/bin/env python3
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
LABEL = f'com.{Path.home().name}.ps5-price-bot'
PLIST = Path.home() / 'Library' / 'LaunchAgents' / (LABEL + '.plist')


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Solo macOS')
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    target = f'gui/{os.getuid()}'
    if action == 'install':
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        (ROOT / 'logs').mkdir(exist_ok=True)
        payload = {
            'Label': LABEL,
            'ProgramArguments': [str(ROOT / '.venv/bin/python'), '-m', 'ps5bot.app'],
            'WorkingDirectory': str(ROOT),
            'RunAtLoad': True,
            'KeepAlive': True,
            'ThrottleInterval': 30,
            'StandardOutPath': '/dev/null',
            'StandardErrorPath': '/dev/null',
            'EnvironmentVariables': {'PYTHONUNBUFFERED': '1'},
        }
        subprocess.run(['launchctl', 'bootout', target+'/'+LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with PLIST.open('wb') as f:
            plistlib.dump(payload, f)
        subprocess.run(['launchctl', 'bootstrap', target, str(PLIST)], check=True)
        print('Instalado:', PLIST)
    elif action == 'uninstall':
        subprocess.run(['launchctl', 'bootout', target+'/'+LABEL], check=False)
        PLIST.unlink(missing_ok=True)
        print('Servicio retirado. Se conservan configuración, historial y logs.')
    elif action == 'restart':
        subprocess.run(['launchctl', 'kickstart', '-k', target+'/'+LABEL], check=True)
    elif action == 'status':
        subprocess.run(['launchctl', 'print', target+'/'+LABEL], check=False)
    else:
        raise SystemExit('Uso: launch_agent.py install|uninstall|restart|status')


if __name__ == '__main__':
    main()
