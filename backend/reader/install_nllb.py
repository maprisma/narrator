"""Install the optional offline translator: pinned CTranslate2 runtime and NLLB-200 1.3B (int8)."""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from install_kokoro import download_asset
from translator import MODEL_DIR, nllb_ready

# OpenNMT's own CTranslate2 conversion of facebook/nllb-200-distilled-1.3B.
# License: CC-BY-NC 4.0 (non-commercial use only); shown before installation.
REVISION = '70f572adafa4794890ce7826156a4209717855af'
BASE = 'https://huggingface.co/OpenNMT/nllb-200-distilled-1.3B-ct2-int8/resolve/' + REVISION + '/'
ASSETS = [
    ('config.json', 'bb11352c2579e31d4251500cd3d813beb6ab083c8a60268db52e9698c1c9cda2'),
    ('shared_vocabulary.json', 'af53bfd0e6f726209e7325e45b87ab3b14e5856f7d42d7b9be91de3287c45267'),
    ('tokenizer.json', 'e316b82de11d0f951f370943b3c438311629547285129b0b81dadabd01bca665'),
    ('model.bin', '89dc4b9eb7f4dcd3ff36023c9b1c55fcecb47ddc0df97ab31b068ef9cf194940'),
]
PACKAGES = ['ctranslate2==4.8.2', 'tokenizers==0.23.3']


def install(progress=None):
    def report(message):
        print(message, flush=True)
        if progress:
            path = Path(progress)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps({'message': message}))
            temp.replace(path)
    if not all(importlib.util.find_spec(name) for name in ('ctranslate2', 'tokenizers')):
        report('Installing offline translation runtime…')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', *PACKAGES],
                       check=True, timeout=900, stdout=sys.stderr)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, digest in ASSETS:
        download_asset(name, BASE, digest, MODEL_DIR, report)
    report('Checking offline translation…')
    from translator import translate_nllb
    if not translate_nllb('en', 'de', 'Hello.').strip():
        raise ValueError('The offline translator returned no text')
    report('Offline translator installed')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--progress')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        sys.exit(0 if (nllb_ready() if args.check else install(args.progress)) else 1)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Offline translator installation failed: {error}', file=sys.stderr)
        sys.exit(1)
