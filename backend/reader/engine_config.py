"""User-selected files for optional speech engines; no shell command strings."""
import os
from pathlib import Path

PATH_KEYS = {'piper_runner', 'piper_model', 'piper_config', 'qwen_runner',
             'qwen_model', 'qwen_projection', 'qwen_speaker'}


def normalize_path(value):
    if not isinstance(value, str) or len(value) > 4096 or any(c in value for c in '\x00\n\r'):
        raise ValueError('Enter a valid file path')
    if not value.strip():
        return ''
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise ValueError('Use an absolute file path or ~/')
    return str(path)


def engine_files(settings, engine):
    keys = ('piper_runner', 'piper_model', 'piper_config') if engine == 'piper' else (
        'qwen_runner', 'qwen_model', 'qwen_projection', 'qwen_speaker')
    paths = [Path(settings.get(key) or '/nonexistent-screen-narrator-file') for key in keys]
    return paths


def engine_ready(settings, engine):
    paths = engine_files(settings, engine)
    try:
        return all(path.is_file() and path.stat().st_size for path in paths) and os.access(paths[0], os.X_OK)
    except OSError:
        return False
