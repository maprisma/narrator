"""One-shot private IPC and first-use setup for Maprisma Narrator."""
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from setup_backend import DATA, ROOT, missing_packages, runtime_ready, setup_state, setup_pid
import languages

COMMANDS = {'status', 'on', 'off', 'toggle', 'read', 'pause', 'select-area', 'clear-area',
            'configure', 'configure-token', 'online-models', 'install-kokoro',
            'cancel-kokoro-install', 'setup', 'cancel-setup', 'test-voice',
            'check-kokoro-updates', 'update-kokoro', 'test-provider', 'use-provider', 'probe-provider',
            'test-translation', 'translator-models', 'install-translator', 'cancel-translator-install',
            'configure-translator-token', 'paste'}
PASTE_LIMIT = 8 * 1024
PASTE_TYPES = ('text/plain;charset=utf-8', 'text/plain', 'UTF8_STRING', 'TEXT', 'STRING')


def run_bounded(args, limit, timeout):
    """Run a helper with an output cap and one overall deadline: (returncode, bytes).
    Raises ValueError when the output is too large and TimeoutError when it is too slow."""
    deadline = time.monotonic() + timeout
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    chunks, size = [], 0
    try:
        os.set_blocking(proc.stdout.fileno(), False)
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError('took too long')
            try:
                chunk = os.read(proc.stdout.fileno(), 4096)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError('too large')
            chunks.append(chunk)
        return proc.wait(timeout=max(0.1, deadline - time.monotonic())), b''.join(chunks)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()


def read_clipboard():
    """Explicit paste (Ctrl+V in a popup field): plain text from the Wayland clipboard,
    at most 8 KiB within 2 seconds. Text fields never read the clipboard on their own."""
    try:
        code, offered = run_bounded(['wl-paste', '--list-types'], 4096, 1.0)
    except (OSError, ValueError, TimeoutError):
        return dict(clipboard='')
    if code != 0:
        return dict(clipboard='')  # empty clipboard
    types = offered.decode('utf-8', 'replace').split()
    mime = next((t for t in PASTE_TYPES if t in types), None)
    if not mime:
        return dict(clipboard='')
    try:
        code, data = run_bounded(['wl-paste', '--no-newline', '--type', mime], PASTE_LIMIT, 2.0)
    except ValueError:
        raise ValueError('Clipboard text is longer than 8 KiB; paste a shorter value.')
    except TimeoutError:
        raise ValueError('The clipboard did not answer in time.')
    text = data.decode('utf-8', 'replace') if code == 0 else ''
    return dict(clipboard=''.join(c for c in text if c >= ' ' and c != '\x7f'))


def socket_request(payload):
    endpoint = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'kindle-reader/control.sock'
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(8)
        for attempt in range(50):
            try:
                client.connect(str(endpoint))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if attempt == 0:
                    subprocess.run(['systemctl', '--user', 'start', 'ocrvox.service'], check=True,
                                   timeout=10, stdout=subprocess.DEVNULL)
                time.sleep(.1)
        else:
            raise ValueError('Reader did not become ready. Run setup to repair it.')
        client.sendall((json.dumps(payload) + '\n').encode())
        chunks = bytearray()
        while b'\n' not in chunks:
            part = client.recv(65536)
            if not part:
                break
            chunks.extend(part)
            if len(chunks) > 1048576:
                raise ValueError('Reader response too large')
        return json.loads(chunks.split(b'\n', 1)[0])


def _matches_installed(source_dir, app):
    for source in source_dir.glob('*.py'):
        if source.name.startswith('test_'):
            continue
        try:
            if source.read_bytes() != (app / source.name).read_bytes():
                return False
        except OSError:
            return False
    return True


def readiness(language):
    app = DATA / 'app'
    current = _matches_installed(ROOT / 'reader', app)
    if not current and os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        omarchy = Path.home() / '.config/omarchy/plugins/ubruckhaus.simple-reader/reader'
        if omarchy.is_dir():
            current = _matches_installed(omarchy, app)
    return dict(backend_ready=runtime_ready() and current,
                missing_packages=missing_packages(language))


def request(payload):
    command = payload.get('command', 'status')
    if command not in COMMANDS:
        raise ValueError('Unknown command')
    if command == 'paste':
        return read_clipboard()
    setup = setup_state()
    if command == 'setup':
        language = payload.get('language', languages.default_language())
        if not languages.valid(language):
            raise ValueError('Choose a supported language')
        backend_only = payload.get('backend_only', False)
        if not isinstance(backend_only, bool):
            raise ValueError('Invalid setup option')
        engine = payload.get('engine')
        if engine not in (None, 'piper'):
            raise ValueError('Unsupported installer')
        if engine == 'piper' and language not in languages.PIPER:
            raise ValueError('Piper has no voice for this language; use Kokoro')
        translator = payload.get('translator')
        if translator not in (None, 'nllb'):
            raise ValueError('Unsupported translator')
        ocr_language = payload.get('ocr_language')
        if ocr_language is not None and not languages.valid(ocr_language):
            raise ValueError('Choose a supported language')
        if not setup.get('busy'):
            DATA.mkdir(parents=True, exist_ok=True)
            with (DATA / 'setup.log').open('a') as log:
                args = [sys.executable, str(ROOT / 'setup_backend.py'), '--language', language]
                if backend_only:
                    args.append('--backend-only')
                if engine:
                    args.extend(['--engine', engine])
                if ocr_language:
                    args.extend(['--ocr-language', ocr_language])
                if translator:
                    args.extend(['--translator', translator])
                subprocess.Popen(args,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            return dict(setup_busy=True, setup_message='Starting setup…', enabled=False, settings={})
    elif command == 'cancel-setup':
        if setup.get('busy') and setup.get('phase') == 'packages':
            raise ValueError('Wait for the package transaction to finish before cancelling.')
        if setup.get('busy') and setup_pid(setup.get('pid')):
            os.kill(setup['pid'], signal.SIGTERM)
    elif command != 'status' and setup.get('busy'):
        raise ValueError('Wait for setup to finish before reading or changing settings.')
    endpoint = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'kindle-reader/control.sock'
    if setup.get('busy') or (command in ('status', 'cancel-setup', 'setup') and not endpoint.exists() and not runtime_ready()):
        try:
            config = json.loads((Path.home() / '.config/kindle-reader/settings.json').read_text())
        except (OSError, ValueError):
            config = {}
        response = dict(enabled=False, status='Ready to set up local reading', settings=config)
    else:
        try:
            response = socket_request(payload if command not in ('setup', 'cancel-setup') else {'command': 'status'})
        except (OSError, subprocess.SubprocessError) as error:
            if command != 'status':
                raise
            response = dict(enabled=False, status='Reader could not start. Run setup to repair it. ' + str(error), settings={})
    response.setdefault('settings', {}).setdefault('language', languages.default_language())
    response.setdefault('languages', languages.options())
    response.update(readiness(response['settings']['language']))
    setup = setup_state()
    response.update(setup_busy=setup.get('busy', False), setup_message=setup.get('message', ''),
                    setup_phase=setup.get('phase', 'idle'))
    return response


if __name__ == '__main__':
    os.umask(0o077)
    try:
        print(json.dumps(request(json.loads(sys.stdin.readline()))))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}))
