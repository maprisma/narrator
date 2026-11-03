"""Install only the selected Kokoro language model into the reader runtime."""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from languages import JAPANESE_MODULES, JAPANESE_PACKAGES, KOKORO, kokoro_family

STANDARD = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'
GERMAN_REVISION = 'a1cba7fbf0e72fbae38f0a3a48ce0dc8e6077804'
GERMAN = 'https://huggingface.co/Godelaune/Kokoro-82M-ONNX-German-Martin/resolve/' + GERMAN_REVISION + '/'
# Model families: 'de' is the German Martin model, 'en' the standard multilingual model.
ASSETS = {
    'de': [('kokoro-martin.onnx', GERMAN, 'c302f1d8bc7adf40a842cb550e18c39a5026bdb1afdd29dbb700b501cb49276b'),
           ('voices-martin.npz', GERMAN, '5b9c8553398d7abf67498ce500c186cefaa7b68fed3e3d415da5380670105acd')],
    'en': [('kokoro-v1.0.onnx', STANDARD, 'beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a'),
           ('voices-v1.0.bin', STANDARD, 'bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d')]
}


def valid_asset(path, expected):
    try:
        with Path(path).open('rb') as data:
            return hashlib.file_digest(data, 'sha256').hexdigest() == expected
    except OSError:
        return False


def download_asset(name, base, digest, folder, report):
    target = folder / name
    if valid_asset(target, digest):
        report(f'{name}: already installed')
        return
    fd, temporary = tempfile.mkstemp(prefix='.kokoro-download-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(base + name, timeout=60) as response:
            total = int(response.headers.get('Content-Length', 0))
            received, last_percent = 0, -1
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
                received += len(chunk)
                percent = int(received * 100 / total) if total else 0
                if percent != last_percent:
                    report(f'Downloading {name}: {percent}%' if total else f'Downloading {name}: {received // (1024 * 1024)} MB')
                    last_percent = percent
        if not valid_asset(temporary, digest):
            raise ValueError(f'{name}: checksum verification failed')
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_launcher():
    launcher = Path.home() / '.local/bin/kindle-kokoro-tts'
    if launcher.exists():
        try:
            previous = launcher.read_text()
        except (OSError, UnicodeError):
            return
        markers = ('Kindle Reader Kokoro-82M TTS Wrapper', 'Managed by Read Aloud', 'Managed by ubruckhaus.simple-reader')
        if not any(marker in previous for marker in markers):
            return
    launcher.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name('kokoro_tts.py').resolve()
    launcher.write_text('#!' + sys.executable + '\n# Managed by ubruckhaus.simple-reader\n' +
                        'import sys, runpy\n' +
                        'sys.path.insert(0, ' + repr(str(source.parent)) + ')\n' +
                        'runpy.run_path(' + repr(str(source)) + ', run_name="__main__")\n')
    launcher.chmod(0o755)


def install(language, progress=None, check_only=False):
    if language not in KOKORO:
        raise ValueError('Kokoro has no voice for this language; use Piper')
    japanese = language == 'ja'
    language = kokoro_family(language)
    folder = Path.home() / '.local/share/kindle-reader/kokoro'
    def report(message):
        print(message, flush=True)
        if progress:
            path = Path(progress)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps({'message': message}))
            temp.replace(path)
    dependencies = all(importlib.util.find_spec(name) for name in ('kokoro_onnx', 'soundfile', 'onnxruntime'))
    japanese_ready = all(importlib.util.find_spec(name) for name in JAPANESE_MODULES)
    from kokoro_updates import active_models, model_paths, update
    active = active_models().get(language, {})
    if check_only:
        if active:
            return dependencies and all(valid_asset(path, active.get('digests', {}).get(path.name, '')) for path in model_paths(language))
        return dependencies and (japanese_ready or not japanese) and all(valid_asset(folder / name, digest) for name, _, digest in ASSETS[language])
    folder.mkdir(parents=True, exist_ok=True)
    if not dependencies:
        report('Installing Kokoro runtime dependencies…')
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'kokoro-onnx==0.4.7', 'soundfile==0.14.0'],
                       check=True, timeout=900)
    if japanese and not japanese_ready:
        report('Installing Japanese pronunciation dictionary (about 270 MB)…')
        # unidic-lite is a pure-data source package; everything else is a wheel.
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--prefer-binary', *JAPANESE_PACKAGES],
                       check=True, timeout=1800, stdout=sys.stderr)
    # Setup/repair must not silently revert a model installed by Update.
    if active:
        if not all(valid_asset(path, active.get('digests', {}).get(path.name, '')) for path in model_paths(language)):
            update(language, progress)
    else:
        for asset in ASSETS[language]:
            download_asset(*asset, folder, report)
    write_launcher()
    report('Kokoro installed. Select a voice to start reading.')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--language', choices=sorted(KOKORO), required=True)
    parser.add_argument('--progress')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        sys.exit(0 if install(args.language, args.progress, args.check) else 1)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Kokoro installation failed: {error}', file=sys.stderr)
        sys.exit(1)
