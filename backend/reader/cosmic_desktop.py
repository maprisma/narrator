#!/usr/bin/env python3
"""The desktop side of reading on COSMIC, through the Screen Narrator desktop service (D-Bus),
which the COSMIC panel applet starts.

Stands in for the Hyprland tools; each command prints what that tool printed:
  active-window              hyprctl activewindow -j (address, pid, at, size, title, class,
                             plus focused and shown: on the current workspace, not minimized)
  window ADDRESS             the same for that window, {} once it is closed
  clients                    hyprctl clients -j
  capture X,Y WxH FILE       grim -g "X,Y WxH" FILE
  capture-window ADDRESS X,Y WxH FILE
                             that part of the window, even with other windows over it
  select-area                slurp: "X,Y WxH", exit 1 when cancelled
  send-key ADDRESS KEY       a key (X keysym name) to that window; it gets the focus for a
                             moment if needed, but only when it is on the current workspace
  open-settings              the settings window (Flutter)
Stdlib only: it runs with the reader's Python.
"""
import json
import subprocess
import sys

NAME = 'io.github.ubruckhaus.ScreenNarrator'
PATH = '/io/github/ubruckhaus/ScreenNarrator'
INTERFACE = 'io.github.ubruckhaus.ScreenNarrator.Desktop'
# Area selection waits for the user; everything else answers at once.
TIMEOUTS = {'SelectArea': 90}


def call(method, signature='', *args):
    argv = ['busctl', '--user', '--json=short', f'--timeout={TIMEOUTS.get(method, 5)}',
            'call', NAME, PATH, INTERFACE, method]
    if signature:
        argv += [signature, *map(str, args)]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUTS.get(method, 5) + 5)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'The Screen Narrator desktop service is not running (add the Screen Narrator applet to the COSMIC panel)')
    data = json.loads(result.stdout)['data']
    return data[0] if data else None


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    command, rest = argv[0], argv[1:]
    try:
        if command == 'active-window':
            print(call('ActiveWindow'))
        elif command == 'window' and len(rest) == 1:
            print(call('Window', 's', rest[0]))
        elif command == 'clients':
            print(call('Clients'))
        elif command == 'capture' and len(rest) == 2:
            if not call('Capture', 'ss', rest[0], rest[1]):
                raise RuntimeError('Screen capture failed')
        elif command == 'capture-window' and len(rest) == 3:
            if not call('CaptureWindow', 'sss', *rest):
                raise RuntimeError('The reading window is not on screen')
        elif command == 'select-area':
            area = call('SelectArea')
            if not area:
                return 1
            print(area)
        elif command == 'send-key' and len(rest) == 2:
            if not call('SendKey', 'ss', rest[0], rest[1]):
                raise RuntimeError('The reading window is not on screen')
        elif command == 'open-settings':
            try:
                call('OpenSettings')
            except RuntimeError:
                from pathlib import Path
                app = Path.home() / '.local/share/cosmic-narrator/settings/screen-narrator-settings'
                subprocess.Popen([str(app) if app.is_file() else 'screen-narrator-settings'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print('Unknown command: ' + ' '.join(argv), file=sys.stderr)
            return 2
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
