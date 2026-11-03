"""Check official Kokoro sources and activate checksum-verified model pairs."""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import sys
import urllib.request
from install_kokoro import ASSETS, download_asset, valid_asset, write_launcher
from languages import KOKORO, kokoro_family

FOLDER = Path.home() / '.local/share/kindle-reader/kokoro'
ACTIVE = FOLDER / 'active-models.json'
HF = 'https://huggingface.co/api/models/Godelaune/Kokoro-82M-ONNX-German-Martin?blobs=true'
GH = 'https://api.github.com/repos/thewh1teagle/kokoro-onnx/releases'
PINNED_GH = {'kokoro-v1.0.onnx': (224414194, '2025-01-28T21:48:53Z'),
             'voices-v1.0.bin': (227558528, '2025-02-09T06:23:03Z')}
HEX = re.compile(r'^[0-9a-f]{64}$')


def metadata(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Read-Aloud-model-update', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Model metadata is too large')
    return json.loads(raw)


def active_models():
    try:
        data = json.loads(ACTIVE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def model_paths(language):
    language = kokoro_family(language)
    record = active_models().get(language)
    names = [asset[0] for asset in ASSETS[language]]
    if isinstance(record, dict):
        folder = (FOLDER / str(record.get('folder', ''))).resolve()
        if folder.is_relative_to((FOLDER / 'versions').resolve()) and all((folder / name).is_file() for name in names):
            return [folder / name for name in names]
    return [FOLDER / name for name in names]


def upstream(language):
    expected = [a[0] for a in ASSETS[language]]
    if language == 'de':
        data = metadata(HF)
        revision = data.get('sha', '')
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('Invalid German model revision')
        files = {s['rfilename']: s for s in data.get('siblings', [])}
        assets = []
        for name in expected:
            digest = files.get(name, {}).get('lfs', {}).get('sha256', '')
            if not HEX.fullmatch(digest):
                raise ValueError('Upstream has no verified checksum for ' + name)
            assets.append((name, 'https://huggingface.co/Godelaune/Kokoro-82M-ONNX-German-Martin/resolve/' + revision + '/', digest))
        return revision, assets
    if language != 'en':
        raise ValueError('Choose German or English')
    releases = metadata(GH + '?per_page=100')
    if not isinstance(releases, list):
        raise ValueError('Invalid release metadata')
    supported = []
    for release in releases:
        match = re.fullmatch(r'model-files-v1\.(\d+)', str(release.get('tag_name', '')))
        names = {a.get('name') for a in release.get('assets', [])}
        if match and not release.get('draft') and not release.get('prerelease') and set(expected) <= names:
            supported.append((int(match[1]), release))
    data = max(supported, key=lambda item: item[0])[1] if supported else metadata(GH + '/tags/model-files-v1.0')
    installed_revision = active_models().get('en', {}).get('revision', '')
    installed_match = re.fullmatch(r'model-files-v1\.(\d+)', installed_revision)
    remote_match = re.fullmatch(r'model-files-v1\.(\d+)', str(data.get('tag_name', '')))
    if installed_match and remote_match and int(installed_match[1]) > int(remote_match[1]):
        data = metadata(GH + '/tags/' + installed_revision)
    revision = data['tag_name']
    if not re.fullmatch(r'model-files-v1\.\d+', revision):
        raise ValueError('Unsupported model release')
    files = {a['name']: a for a in data.get('assets', [])}
    assets = []
    for name, _, pinned_digest in ASSETS['en']:
        asset = files[name]
        digest = str(asset.get('digest') or '').removeprefix('sha256:')
        if not HEX.fullmatch(digest):
            if revision == 'model-files-v1.0' and (asset.get('id'), asset.get('updated_at')) == PINNED_GH[name]:
                digest = pinned_digest
            else:
                raise ValueError('Upstream has no verified checksum for ' + name)
        # Derive download URL from the allowlisted repo, never arbitrary API URLs.
        base = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/' + revision + '/'
        assets.append((name, base, digest))
    return revision, assets


def check(language):
    language = kokoro_family(language)
    revision, assets = upstream(language)
    installed = model_paths(language)
    available = not all(valid_asset(path, asset[2]) for path, asset in zip(installed, assets))
    return dict(language=language, revision=revision, available=available,
                checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                message='Model update available' if available else 'Installed model files are up to date')


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.models-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def update(language, progress=None):
    language = kokoro_family(language)
    revision, assets = upstream(language)
    identifier = hashlib.sha256(''.join(a[2] for a in assets).encode()).hexdigest()[:20]
    destination = FOLDER / 'versions' / (language + '-' + identifier)
    destination.mkdir(parents=True, exist_ok=True)
    def report(message):
        if progress:
            atomic_json(Path(progress), {'message': message})
    for asset in assets:
        download_asset(*asset, destination, report)
    # Construct both model and voice tables before committing the active pair.
    report('Validating downloaded model and voices…')
    with contextlib.redirect_stdout(sys.stderr):
        from kokoro_compat import create, load
        model = load(destination / assets[0][0], destination / assets[1][0])
        voice = 'martin' if language == 'de' else 'af_heart'
        if voice not in model.get_voices():
            raise ValueError('Downloaded model pair is missing its default voice')
        samples, rate = create(model, 'Hallo.' if language == 'de' else 'Hello.', voice,
                               lang='de' if language == 'de' else 'en-us')
        if len(samples) == 0 or rate <= 0:
            raise ValueError('Downloaded model pair failed the speech test')
        del model
    state = active_models()
    state[language] = dict(folder=str(destination.relative_to(FOLDER)), revision=revision,
                           digests={a[0]: a[2] for a in assets})
    write_launcher()
    atomic_json(ACTIVE, state)
    report('Model update installed')
    return dict(language=language, revision=revision, available=False, message='Model update installed')


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--language', choices=sorted(KOKORO), required=True)
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--progress')
    args = parser.parse_args()
    try:
        result = update(args.language, args.progress) if args.update else check(args.language)
        print(json.dumps(result))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
