"""First-use setup, runnable with system Python before the reader exists."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'reader'))
import languages  # noqa: E402  (stdlib only, shared with the reader runtime)
DATA = Path.home() / '.local/share/kindle-reader'
UNIT = Path.home() / '.config/systemd/user/ocrvox.service'
PROGRESS = DATA / 'setup-progress.json'
# Windows and focus come from the COSMIC desktop service; it takes screenshots with grim,
# lets you drag an area with slurp and turns pages with wtype.
PACKAGES = {'magick': 'imagemagick', 'tesseract': 'tesseract', 'mpv': 'mpv',
            'pactl': 'libpulse', 'notify-send': 'libnotify', 'busctl': 'systemd',
            'grim': 'grim', 'slurp': 'slurp', 'wtype': 'wtype'}
MODULES = ('PySide6', 'kokoro_onnx', 'numpy', 'soundfile', 'onnxruntime')
child = None
phase = ''


def missing_packages(language):
    result = [package for command, package in PACKAGES.items() if not shutil.which(command)]
    if shutil.which('tesseract'):
        available = subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True, timeout=10).stdout.split()
        for lang in dict.fromkeys(('eng', languages.ocr_language(language))):
            if lang not in available and not (DATA / 'tessdata' / (lang + '.traineddata')).is_file():
                result.append('tesseract-data-' + lang)
    else:
        result.extend('tesseract-data-' + lang for lang in dict.fromkeys(('eng', languages.ocr_language(language))))
    return list(dict.fromkeys(result))


def runtime_ready():
    python = DATA / 'venv/bin/python'
    if not python.is_file():
        return False
    code = 'import importlib.util; import sys; sys.exit(not all(importlib.util.find_spec(m) for m in ' + repr(MODULES) + '))'
    try:
        return subprocess.run([str(python), '-c', code], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def setup_state():
    try:
        state = json.loads(PROGRESS.read_text())
        if state.get('busy') and not setup_pid(state.get('pid')):
            return dict(busy=False, message='Setup was interrupted. Retry setup.', phase='error')
        return state
    except (OSError, ValueError, TypeError):
        return dict(busy=False, message='', phase='idle')


def setup_pid(pid):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        process = Path('/proc') / str(pid)
        argv = (process / 'cmdline').read_bytes().split(b'\0')
        return process.stat().st_uid == os.getuid() and str(ROOT / 'setup_backend.py').encode() in argv
    except OSError:
        return False


def report(message, stage=None, busy=True):
    global phase
    if stage:
        phase = stage
    DATA.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.setup-', dir=DATA)
    with os.fdopen(fd, 'w') as output:
        json.dump(dict(message=message, phase=phase, busy=busy, pid=os.getpid()), output)
    os.replace(name, PROGRESS)
    print(message, flush=True)


def run(args, stream=False):
    global child
    child = subprocess.Popen([str(a) for a in args], start_new_session=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    try:
        for line in child.stdout:
            tail.append(line.strip())
            tail = tail[-8:]
            if stream:
                report(line.strip())
        if child.wait():
            raise RuntimeError('\n'.join(tail)[-1200:] or 'Command failed: ' + str(args[0]))
    finally:
        child = None


def interrupted(*_):
    if child is not None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    report('Setup cancelled. Installed files are kept; you can retry.', 'cancelled', False)
    raise SystemExit(130)


def managed_service(text):
    return ('Managed by ubruckhaus.simple-reader' in text or
            ('Description=Simple Reader' in text and
             any(path in text for path in ('.local/bin/ocrvox', 'kindle-reader/app/reader.py'))))


def install_launcher(backup):
    """Preserve the desktop ID and command used by existing shortcut bindings."""
    template = (ROOT / 'maprisma-narrator.desktop').read_text()
    launcher = Path.home() / '.local/bin/simple-reader'
    desktop = Path.home() / '.local/share/applications/simple-reader.desktop'
    for path in (launcher, desktop):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, backup / path.name)
    launcher.write_text('#!/usr/bin/env bash\n# Managed by ubruckhaus.simple-reader (Maprisma Narrator)\nexec ' +
                        shlex.quote(str(DATA / 'venv/bin/python')) + ' ' +
                        shlex.quote(str(DATA / 'app/reader.py')) + ' "$@"\n')
    launcher.chmod(0o755)
    desktop.write_text(template)


def install(language, backend_only=False, engine=None, ocr_language=None, translator=None):
    """Set up the reader: OCR data for `ocr_language` (default: `language`) and a voice for `language`."""
    if not languages.valid(language) or not languages.valid(ocr_language or language):
        raise ValueError('Choose a supported language')
    if engine is None and language not in languages.KOKORO:
        engine = 'piper'  # Kokoro has no voice for this language; Piper does.
        backend_only = True
    if engine == 'piper' and language not in languages.PIPER:
        raise ValueError('Piper has no voice for this language; use Kokoro')
    DATA.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    lock = os.open(DATA / 'setup.lock', flags, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock)
        raise RuntimeError('Setup is already running')
    try:
        existing = UNIT.read_text() if UNIT.exists() else ''
        if existing and not managed_service(existing):
            raise RuntimeError('An unmanaged ocrvox.service exists. Its configuration was preserved; choose a different service before setup.')
        packages = missing_packages(ocr_language or language)
        if packages:
            report('Authorize installation of: ' + ', '.join(packages), 'packages')
            run(['pkexec', 'pacman', '-S', '--needed', '--noconfirm', *packages])
        report('Preparing private Python runtime…', 'runtime')
        python = DATA / 'venv/bin/python'
        if not python.exists():
            run([sys.executable, '-m', 'venv', DATA / 'venv'])
        if not runtime_ready():
            run([python, '-m', 'pip', 'install', '-r', ROOT / 'requirements.txt'], stream=True)
        backup = DATA / 'backups' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True)
        report('Updating reader runtime (existing files backed up)…', 'runtime')
        # Stop the known reader before replacing code, preserving service enablement.
        run(['systemctl', '--user', 'stop', 'ocrvox.service']) if existing else None
        app = DATA / 'app'
        app.mkdir(exist_ok=True)
        for source in (ROOT / 'reader').iterdir():
            if source.suffix not in ('.py', '.qml') or source.name.startswith('test_'):
                continue
            target = app / source.name
            if target.exists():
                shutil.copy2(target, backup / source.name)
            fd, temporary = tempfile.mkstemp(prefix='.app-', dir=app)
            os.close(fd)
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        UNIT.parent.mkdir(parents=True, exist_ok=True)
        if existing:
            shutil.copy2(UNIT, backup / 'ocrvox.service')
        else:
            UNIT.write_text('''# Managed by ubruckhaus.simple-reader (Maprisma Narrator)
[Unit]
Description=Maprisma Narrator OCR and speech
PartOf=graphical-session.target
After=graphical-session.target
[Service]
Type=simple
ExecStart=%h/.local/share/kindle-reader/venv/bin/python %h/.local/share/kindle-reader/app/reader.py
Restart=on-failure
RestartSec=3
KillMode=control-group
TimeoutStopSec=5
UMask=0077
''')
        # A managed override updates legacy launchers without replacing their unit.
        drop = UNIT.with_name('ocrvox.service.d')
        drop.mkdir(exist_ok=True)
        override = drop / 'read-aloud-runtime.conf'
        kept = []
        if override.exists():
            shutil.copy2(override, backup / override.name)
            # Keep a user-chosen Qwen model folder across upgrades.
            kept = [line for line in override.read_text().splitlines()
                    if line.startswith('Environment=QWEN_TTS_MODEL_DIR=')][-1:]
        override_text = '''# Managed by ubruckhaus.simple-reader (Maprisma Narrator)
[Service]
ExecStart=
ExecStart=%h/.local/share/kindle-reader/venv/bin/python %h/.local/share/kindle-reader/app/reader.py
Environment=OCRVOX_BAR_WIDGET=1
# No windows of its own: the bar icon is the COSMIC applet, the settings a Flutter app.
Environment=QT_QPA_PLATFORM=offscreen
Environment=PYTHONDONTWRITEBYTECODE=1
'''
        override_text += ''.join(line + '\n' for line in kept)
        override.write_text(override_text)
        install_launcher(backup)
        if not backend_only:
            report('Installing selected Kokoro voice…', 'voice')
            run([python, app / 'install_kokoro.py', '--language', language], stream=True)
        run(['systemctl', '--user', 'daemon-reload'])
        run(['systemctl', '--user', 'start', 'ocrvox.service'])
        if engine == 'piper':
            from install_piper import install as install_voice
            install_voice(DATA, language, run, report)
        if translator == 'nllb':
            report('Installing offline translator (about 1.4 GB)…', 'translator')
            run([python, app / 'install_nllb.py'], stream=True)
        report('Ready. Test provider voice, then choose Use provider.', 'ready', False)
    except Exception as error:
        report('Setup failed: ' + str(error), 'error', False)
        raise
    finally:
        os.close(lock)


if __name__ == '__main__':
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser()
    parser.add_argument('--language', choices=sorted(languages.LANGUAGES), default='de')
    parser.add_argument('--backend-only', action='store_true')
    parser.add_argument('--engine', choices=('piper',))
    parser.add_argument('--ocr-language', choices=sorted(languages.LANGUAGES))
    parser.add_argument('--translator', choices=('nllb',))
    options = parser.parse_args()
    try:
        install(options.language, options.backend_only or options.engine is not None, options.engine, options.ocr_language, options.translator)
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
