"""Install a pinned Piper runtime and one verified voice for the reading language."""
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from install_kokoro import download_asset
from languages import PIPER, PIPER_REVISION, sample

BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/' + PIPER_REVISION + '/'


def installed_settings(data, language):
    name = PIPER[language][1]
    return dict(piper_runner=str(data / 'piper-runtime/bin/piper'),
                piper_model=str(data / 'piper-voices' / name),
                piper_config=str(data / 'piper-voices' / (name + '.json')))


def install(data, language, run, report):
    folder = data / 'piper-voices'
    folder.mkdir(parents=True, exist_ok=True)
    runtime = data / 'piper-runtime'
    python = runtime / 'bin/python'
    report('Preparing separate Piper runtime…', 'runtime')
    if not python.exists():
        run([sys.executable, '-m', 'venv', runtime])
    run([python, '-m', 'pip', 'install', '--only-binary=:all:', 'piper-tts==1.8.0'], stream=True)
    prefix, name, model_digest, config_digest, size = PIPER[language]
    report(f'Downloading Piper voice (about {size} MB)…', 'voice')
    download_asset(name, BASE + prefix, model_digest, folder, report)
    download_asset(name + '.json', BASE + prefix, config_digest, folder, report)
    settings = installed_settings(data, language)
    report('Checking Piper speech generation…', 'voice')
    with tempfile.TemporaryDirectory(prefix='.piper-test-', dir=data) as temporary:
        text = Path(temporary) / 'sample.txt'
        output = Path(temporary) / 'sample.wav'
        text.write_text(sample(language), encoding='utf-8')
        run([settings['piper_runner'], '-m', settings['piper_model'],
             '-c', settings['piper_config'], '--input-file', text, '-f', output])
        with wave.open(str(output)) as audio:
            if audio.getnframes() == 0:
                raise ValueError('Piper generated an empty voice sample')
    return settings
