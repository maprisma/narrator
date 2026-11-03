#!/usr/bin/env python3
"""Kindle Reader Kokoro-82M TTS Wrapper."""
import argparse
import os
import json
import contextlib
import sys
from pathlib import Path

# Add Kokoro directory to sys.path for tts_normalizer and german_text_rules
KOKORO_DIR = Path.home() / '.local/share/kindle-reader/kokoro'
if str(KOKORO_DIR) not in sys.path:
    sys.path.insert(0, str(KOKORO_DIR))

import numpy as np
import soundfile as sf
from kokoro_compat import create, japanese_phonemes, load
from kokoro_updates import model_paths
from languages import kokoro_phonemes

# Cache Kokoro model instances across warm calls if needed, or instantiate per-call
_MODELS = {}

def get_kokoro(voice: str):
    # Martin needs the German model; every other voice is in the standard model.
    model_path, voices_path = map(str, model_paths('de' if voice == 'martin' else 'en'))

    key = (model_path, voices_path)
    if key not in _MODELS:
        _MODELS.clear()  # Keep only the selected language model resident.
        _MODELS[key] = load(model_path, voices_path)
    return _MODELS[key]

def main():
    parser = argparse.ArgumentParser(description="Generate speech using Kokoro-82M ONNX")
    parser.add_argument("-i", "--input", help="Path to text input file")
    parser.add_argument("-p", "--prompt", help="Direct text to speak")
    parser.add_argument("-o", "--output", required=True, help="Path to output WAV file")
    parser.add_argument("-m", "-v", "--voice", default="martin", help="Voice name (e.g. martin, af_heart, af_nicole, am_adam)")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="Speech speed multiplier (0.5 to 2.0)")
    parser.add_argument("-l", "--lang", default="de", help="Language code (e.g. de, en-us, en-gb)")
    args = parser.parse_args()

    if args.input:
        text = Path(args.input).read_text(encoding="utf-8").strip()
    elif args.prompt:
        text = args.prompt.strip()
    else:
        text = sys.stdin.read().strip()

    if not text:
        sys.exit(0)

    synthesize(text, args.voice, args.lang, args.speed, args.output)


def synthesize(text, voice, language, speed, output):
    lang = kokoro_phonemes(language, voice)

    # Normalize German text if reading in German with Martin
    if voice == 'martin' or lang.startswith('de'):
        try:
            import tts_normalizer
            text = tts_normalizer.normalize_text(text)
        except Exception:
            pass

    # Ensure speed is clamped within valid ONNX range
    speed = max(0.5, min(2.0, float(speed)))

    kokoro = get_kokoro(voice)
    try:
        if lang == 'ja':
            samples, sample_rate = create(kokoro, japanese_phonemes(text), voice, speed, lang, is_phonemes=True)
        else:
            samples, sample_rate = create(kokoro, text, voice, speed, lang)
    except Exception as e:
        # Fallback to en-us if requested language phonemizer encounters an issue
        if lang != "en-us" and "No phonemes" in str(e):
            samples, sample_rate = create(kokoro, text, voice, speed, "en-us")
        else:
            raise

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), samples, sample_rate)


def serve():
    """Keep the model resident for successive chunks; stdin EOF releases it."""
    for line in sys.stdin:
        try:
            request = json.loads(line)
            # Libraries may print diagnostics; stdout is reserved for replies.
            with contextlib.redirect_stdout(sys.stderr):
                synthesize(request['text'], request['voice'], request['language'],
                           1.0, request['output'])
            reply = {'code': 0, 'error': ''}
        except Exception as error:
            reply = {'code': 1, 'error': str(error)}
        print(json.dumps(reply), flush=True)

if __name__ == "__main__":
    if sys.argv[1:] == ['--worker']:
        serve()
    else:
        main()
