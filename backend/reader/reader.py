#!/usr/bin/env python3
"""Local, active-window OCR narration; the Screen Narrator COSMIC applet is its bar icon and desktop side."""
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from highlighting import HighlightOverlay, chunk_rectangles, visible_ocr
from online_provider import endpoint_url, saved_token, store_token
from speech_worker import SpeechWorker
from engine_config import PATH_KEYS, normalize_path, engine_files, engine_ready
from kokoro_updates import model_paths
from audio_output import outputs, validate_output, playback_output
from install_piper import installed_settings
import languages
from languages import KOKORO, PIPER, kokoro_voice_language
from translator import nllb_ready
from pdf_page import find_page_in_image, viewer_keys

from PySide6.QtCore import QObject, QProcess, QTimer, Qt, QLockFile
from PySide6.QtGui import QActionGroup
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu

HOME = Path.home()
DATA = HOME / '.local/share/kindle-reader'
CONFIG = HOME / '.config/kindle-reader/settings.json'
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'kindle-reader'
# The focused window, screenshots, area selection and keys come from the COSMIC desktop service (cosmic_desktop.py).
DESKTOP = [sys.executable, str(Path(__file__).with_name('cosmic_desktop.py'))]
# Focused when reading starts, but never the book: the settings window and the panel.
NOT_BOOKS = {'io.github.ubruckhaus.ScreenNarratorSettings', 'screen-narrator-settings', 'com.system76.CosmicPanel',
             'com.system76.CosmicLauncher', 'com.system76.CosmicAppLibrary'}
QWEN_MODEL_DIR = Path(os.environ.get('QWEN_TTS_MODEL_DIR', DATA / 'models/Qwen3-TTS-1.7B'))
VOICES = {
    'piper-custom': ('Custom Piper voice', 'piper', 'custom'),
    'qwen-custom': ('Custom Qwen voice', 'qwen', 'custom'),
    'kokoro-martin': ('Martin · male · Kokoro', 'kokoro', 'martin'),
    'kokoro-heart': ('Heart · female · Kokoro', 'kokoro', 'af_heart'),
    'kokoro-nicole': ('Nicole · female · Kokoro', 'kokoro', 'af_nicole'),
    'kokoro-adam': ('Adam · male · Kokoro', 'kokoro', 'am_adam'),
    'kerstin-fast': ('Kerstin · female · fast', 'piper', 'de_DE-kerstin-low.onnx'),
    'thorsten-fast': ('Thorsten · male · fast', 'piper', 'de_DE-thorsten-high.onnx'),
    'lessac-fast': ('Lessac · English · Piper Fast', 'piper', 'en_US-lessac-high.onnx'),
    'qwen-kerstin': ('Kerstin · female · Qwen 1.7B', 'qwen', 'kerstin-reference.wav'),
    'qwen-thorsten': ('Thorsten · male · Qwen 1.7B', 'qwen', 'thorsten-reference.wav'),
}
# Kokoro voices for the other catalog languages; legacy keys above stay unchanged.
for _code, (_family, _phonemes, _voices) in KOKORO.items():
    for _voice, _label in _voices:
        if not any(entry[2] == _voice for entry in VOICES.values()):
            VOICES['kokoro-' + _voice] = (_label + ' · Kokoro', 'kokoro', _voice)
# Piper voices installed by guided setup (one per language) are ordinary voices too.
for _code, (_prefix, _file, *_rest) in PIPER.items():
    VOICES['piper-' + _code] = (_file.split('-')[1].replace('_', ' ').title() + ' · Piper', 'piper', 'managed:' + _code)
DEFAULTS = dict(audio_output='auto', voice='kokoro-martin', speed=1.0, language=languages.default_language(), follow=True, kindle_crop=True, pdf_page_area=True, auto_page_turn=True, kindle_area=None, highlight=True, provider='Local', online_endpoint='https://api.openai.com/v1', online_model='', online_voice='alloy', remember_token=False, piper_runner=str(DATA / 'venv/bin/piper'), piper_model='', piper_config='', qwen_runner=str(HOME / '.local/bin/llama-tts'), qwen_model=str(QWEN_MODEL_DIR / 'Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf'), qwen_projection=str(QWEN_MODEL_DIR / 'mmproj-Qwen3-TTS-12Hz-1.7B-Base-bf16.gguf'), qwen_speaker='',
                translate_to='', translator='llm', translator_endpoint='http://127.0.0.1:8080/v1',
                translator_model='', remember_translator_token=False)
TRANSLATOR_ENDPOINTS = {'llama.cpp': 'http://127.0.0.1:8080/v1', 'LM Studio': 'http://127.0.0.1:1234/v1',
                        'Ollama': 'http://127.0.0.1:11434/v1'}


def speech_language(settings):
    """The voice speaks the translation target when translation is on, else the text language."""
    return settings.get('translate_to') or settings['language']


def voice_is_available(key, settings=None):
    """Offer only voices with their own usable engine and required assets."""
    entry = VOICES.get(key)
    if not entry:
        return False
    _, engine, reference = entry
    if reference == 'custom':
        if settings is None:
            try:
                settings = json.loads(CONFIG.read_text())
            except (OSError, ValueError):
                settings = {}
        return engine_ready(settings, engine)
    def executable(path):
        return Path(path).is_file() and os.access(path, os.X_OK)
    def present(path):
        try:
            return Path(path).is_file() and Path(path).stat().st_size > 0
        except OSError:
            return False
    if engine == 'kokoro':
        if not executable(HOME / '.local/bin/kindle-kokoro-tts'):
            return False
        if not all(importlib.util.find_spec(name) is not None for name in ('kokoro_onnx', 'soundfile', 'onnxruntime')):
            return False
        if kokoro_voice_language(reference) == 'ja' and not all(importlib.util.find_spec(name) for name in languages.JAPANESE_MODULES):
            return False
        return all(present(path) for path in model_paths(kokoro_voice_language(reference) or 'en'))
    if engine == 'piper' and reference.startswith('managed:'):
        return engine_ready(installed_settings(DATA, reference.split(':', 1)[1]), 'piper')
    if engine == 'piper':
        return executable(DATA / 'venv/bin/piper') and all(present(DATA / 'voices' / name) for name in (reference, reference + '.json'))
    if engine == 'qwen':
        runner = HOME / '.local/bin/llama-tts'
        if not executable(runner):
            return False
        models = ('Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf', 'mmproj-Qwen3-TTS-12Hz-1.7B-Base-bf16.gguf')
        return all(present(QWEN_MODEL_DIR / name) for name in models) and present(DATA / 'voices' / reference)
    return False


def available_voices(language=None, settings=None):
    def matches(value):
        _, engine, reference = value
        if not language:
            return True
        if engine == 'qwen':
            return language in languages.QWEN_LANGUAGES
        if reference == 'custom':
            # A custom Piper voice speaks the language in its file name (nl_NL-…); unknown names stay offered.
            match = re.match(r'([a-z]{2})_', Path((settings or {}).get('piper_model') or '').name)
            return not match or match.group(1) == language
        if engine == 'kokoro':
            return kokoro_voice_language(reference) == language
        if reference.startswith('managed:'):
            return reference.split(':', 1)[1] == language
        return reference.startswith(language + '_')
    result = {key: value for key, value in VOICES.items() if (voice_is_available(key, settings) if settings is not None else voice_is_available(key)) and matches(value)}
    if settings and 'piper-custom' in result:
        model = Path(settings.get('piper_model') or '').name
        label = next((piper_file.split('-')[1].replace('_', ' ').title() + ' · ' + languages.name(code) + ' · Piper'
                      for code, (_, piper_file, *_rest) in PIPER.items() if piper_file == model),
                     'Piper · ' + (model or 'custom voice'))
        result['piper-custom'] = (label, 'piper', 'custom')
        # The same file installed by setup is already listed as its managed voice.
        if any(key == 'piper-' + code and installed_settings(DATA, code)['piper_model'] == settings.get('piper_model')
               for key in list(result) for code in PIPER):
            del result['piper-custom']
    if settings and 'qwen-custom' in result:
        speaker = Path(settings.get('qwen_speaker') or '').stem
        result['qwen-custom'] = ('Qwen · ' + (speaker or 'custom speaker'), 'qwen', 'custom')
    return result


def plain_text(text, limit=300):
    """Notification daemons render markup, so drop markup and control characters."""
    return re.sub(r'[<>&\x00-\x1f\x7f]+', ' ', str(text)).strip()[:limit]


_OCR_LANGUAGES = {'checked': 0.0, 'names': set()}


def ocr_languages():
    """Tesseract languages installed system-wide or in the reader's tessdata (cached briefly)."""
    if time.monotonic() - _OCR_LANGUAGES['checked'] > 30:
        names = set()
        try:
            names = set(subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True,
                                       timeout=5).stdout.split()[1:])
        except (OSError, subprocess.SubprocessError):
            pass
        names |= {path.stem for path in (DATA / 'tessdata').glob('*.traineddata')}
        _OCR_LANGUAGES.update(checked=time.monotonic(), names=names)
    return _OCR_LANGUAGES['names']


_REACHABLE = {}


def translator_reachable(endpoint):
    """Whether a local translation server accepts connections (cached 5 s). Remote HTTPS
    servers are not probed here; Test translation and reading report their errors."""
    import urllib.parse
    url = urllib.parse.urlsplit(endpoint)
    if url.hostname not in ('127.0.0.1', 'localhost', '::1'):
        return True
    key = (url.hostname, url.port or (443 if url.scheme == 'https' else 80))
    checked, ok = _REACHABLE.get(key, (0.0, False))
    if time.monotonic() - checked > 5:
        try:
            with socket.create_connection(key, timeout=0.3):
                ok = True
        except OSError:
            ok = False
        _REACHABLE[key] = (time.monotonic(), ok)
    return ok


NOTICES = []  # recent warnings/errors, also shown inside the popup (notifications sit behind it)


def recent_notices(seconds=120):
    cutoff = time.time() - seconds
    return [n for n in NOTICES if n['time'] >= cutoff]


def install_size(code):
    """Rough download size for the guided voice install of a language."""
    if code in KOKORO:
        return 'about 340 MB' + (' plus a 270 MB dictionary' if code == 'ja' else '')
    return 'about ' + str(PIPER[code][4]) + ' MB' if code in PIPER else 'download'


def well_formed_window(window):
    """True for {} (the extension's answer for a closed window) or a window entry whose
    fields have the types the reader uses: an address, and integer geometry as Mutter gives it."""
    if not isinstance(window, dict):
        return False
    if not window:
        return True
    def pair(value, low):
        return (isinstance(value, list) and len(value) == 2 and
                all(type(n) is int and low <= n <= 1_000_000 for n in value))
    address = window.get('address')
    return (isinstance(address, str) and bool(address) and
            all(isinstance(window.get(key, ''), str) for key in ('title', 'class')) and
            pair(window.get('at'), -1_000_000) and pair(window.get('size'), 1))


def desktop_notify(summary, body='', icon=None, timeout=None, level='info'):
    """Send every notification through one sanitized notify-send call."""
    if level in ('warning', 'error'):
        text = plain_text(body or summary, 500)
        # Millisecond ids keep increasing across reader restarts, so dismissing stays correct.
        NOTICES.append(dict(id=max(int(time.time() * 1000), (NOTICES[-1]['id'] + 1) if NOTICES else 0), time=time.time(), level=level,
                            title=plain_text(summary, 120), text=text))
        del NOTICES[:-5]
    args = ['notify-send', '-a', 'Screen Narrator']
    if icon:
        args += ['-i', icon]
    if timeout:
        args += ['-t', str(timeout)]
    args.append(plain_text(summary))
    if body:
        args.append(plain_text(body))
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# A page number line: "12", "- 12 -", "Page 3", "Seite 3 von 10", "3 / 10", "xiv".
PAGE_NUMBER = re.compile(
    r'[-–—\s]*(?:(?:page|seite|página|pagina|pág\.?|pag\.?|p\.|s\.|strona|side|sida|sivu|oldal|stránka|'
    r'страница|стр\.?|sayfa|halaman|trang|ページ|页|頁|페이지)\s*)?'
    r'(?:\d{1,4}|(?-i:[ivxlc]{1,6}))(?:\s*(?:/|of|von|de|di|z|av|af|из)\s*\d{1,4})?\s*(?:頁|页)?[-–—\s]*',
    re.IGNORECASE)


def strip_page_numbers(text):
    """Drop page number lines at the top and bottom of a page; they are not read aloud."""
    lines = text.split('\n')
    while lines and (not lines[0].strip() or PAGE_NUMBER.fullmatch(lines[0].strip())):
        lines.pop(0)
    while lines and (not lines[-1].strip() or PAGE_NUMBER.fullmatch(lines[-1].strip())):
        lines.pop()
    return '\n'.join(lines)


def clean_text(text):
    # Keep words and punctuation; fix hyphenated line wrapping.
    text = text.replace('\x0c', '').replace('\u00ad', '')
    text = strip_page_numbers(text)
    # Rejoin hyphenated line wraps (e.g. 'Raum-\nschiffs' -> 'Raumschiffs')
    text = re.sub(r'(\b\w+)-\s*\n\s*(\w+\b)', r'\1\2', text)
    paragraphs = re.split(r'\n\s*\n', text.strip())
    cleaned_paras = []
    for p in paragraphs:
        lines = p.splitlines()
        filtered = []
        for line in lines:
            line_str = line.strip()
            # Ignore Kindle footer progress bar and pure symbol/divider lines
            if re.match(r'^Position \d+ von \d+', line_str):
                continue
            if re.match(r'^[—\s\-=_.*#~]+$', line_str) and len(line_str) > 2:
                continue
            filtered.append(line_str)
        if filtered:
            cleaned_paras.append(' '.join(' '.join(filtered).split()))
    return '\n\n'.join(p for p in cleaned_paras if p.strip())


def split_sentences(paragraph):
    pattern = r'([.!?]+[»"\'”’«]?)\s+(?=[A-ZÄÖÜ»„"\'“0-9])'
    parts = re.split(pattern, paragraph)
    sentences = []
    i = 0
    while i < len(parts):
        s = parts[i]
        if i + 1 < len(parts):
            punct = parts[i + 1]
            sentences.append((s + punct).strip())
            i += 2
        else:
            if s.strip():
                sentences.append(s.strip())
            i += 1
    return [s for s in sentences if s]


def split_clause(sentence, limit):
    if len(sentence) <= limit:
        return [sentence]
    clauses = re.split(r'(?<=[,;:\—])\s+', sentence)
    if len(clauses) <= 1:
        words = sentence.split()
        res = []
        cur = ''
        for w in words:
            if cur and len(cur) + len(w) + 1 > limit:
                res.append(cur)
                cur = w
            elif cur:
                cur += ' ' + w
            else:
                cur = w
        if cur:
            res.append(cur)
        return res
    res = []
    cur = ''
    for c in clauses:
        if cur and len(cur) + len(c) + 1 > limit:
            res.append(cur)
            cur = c
        elif cur:
            cur += ' ' + c
        else:
            cur = c
    if cur:
        res.append(cur)
    return res


def chunks(text, limit=250):
    """Whole-sentence chunks keep speech completely natural and avoid model token limits."""
    result = []
    for paragraph in text.split('\n\n'):
        sentences = split_sentences(paragraph)
        current = ''
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > limit:
                if current:
                    result.append(current)
                    current = ''
                for sub in split_clause(sentence, limit):
                    result.append(sub)
                continue
            if current and len(current) + len(sentence) + 1 > limit:
                result.append(current)
                current = sentence
            elif current:
                current = current + ' ' + sentence
            else:
                current = sentence
        if current:
            result.append(current)
    return [chunk for chunk in result if any(c.isalnum() for c in chunk)]


def page_chunks(text):
    result = chunks(text)
    # Start with a short sentence/clause; retain normal lookahead chunk sizes.
    return chunks(result[0], 110) + result[1:] if result else []


def same_text(a, b, threshold=0.90):
    a, b = ' '.join(a.split()), ' '.join(b.split())
    if a == b:
        return True
    if not a or not b:
        return False
    return bool(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= threshold)


class Task(QObject):
    """One cancellable subprocess. A killed process never invokes its callback."""
    def __init__(self, owner, args, done, timeout=180, stdin_data=None, close_stdin=False):
        super().__init__(owner)
        self.owner, self.done, self.cancelled = owner, done, False
        if close_stdin:
            # QProcess hands every child a pipe on stdin. slurp treats a piped stdin as
            # "restrict boxes from stdin" mode: it blocks reading stdin and never grabs
            # the pointer. Redirect stdin from /dev/null (QProcess cannot attach a file
            # to stdin) to force interactive mode. `exec` keeps the PID stable so
            # Task.cancel()/expire() still kill the real process directly.
            script = 'exec ' + ' '.join(shlex.quote(str(a)) for a in args) + ' </dev/null'
            args = ['sh', '-c', script]
        self.proc = QProcess(self)
        self.proc.setProgram(str(args[0]))
        self.proc.setArguments([str(a) for a in args[1:]])
        self.proc.finished.connect(self.finish)
        self.proc.errorOccurred.connect(self.error)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.expire)
        owner.tasks.add(self)
        self.proc.start()
        if stdin_data is not None:
            data = stdin_data.encode('utf-8') if isinstance(stdin_data, str) else stdin_data
            self.proc.write(data)
            self.proc.closeWriteChannel()
        self.timer.start(timeout * 1000)

    def error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.finish(-1)

    def expire(self):
        self.proc.kill()

    def finish(self, code, *_):
        if self not in self.owner.tasks:
            return
        self.timer.stop()
        self.owner.tasks.discard(self)
        out = bytes(self.proc.readAllStandardOutput()).decode(errors='replace')
        err = bytes(self.proc.readAllStandardError()).decode(errors='replace')
        if not self.cancelled:
            try:
                self.done(code, out, err)
            except Exception as e:
                print(f'Task callback error: {e}', file=sys.stderr, flush=True)
        self.deleteLater()

    def cancel(self):
        self.cancelled = True
        self.proc.kill()
        self.proc.waitForFinished(1000)


class Reader(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.tasks = set()
        self.speech_tasks = set()
        self.testing_voice = False
        self.preview_original = None
        self.preview_token = None
        self.preview_settings = None
        self.verified_provider = None
        self.verified_token_digest = None
        self.probed_settings = {}
        self.probed_voices = []
        self.kokoro_worker = SpeechWorker(self)
        app.aboutToQuit.connect(self.kokoro_worker.close)
        self.translation_worker = SpeechWorker(self, 'translator.py', 'Translation')
        app.aboutToQuit.connect(self.translation_worker.close)
        self.translation_status = ''
        self.translator_models = []
        self.translator_models_loading = False
        self.installing_translator = False
        self.translator_install_task = None
        self.settings = DEFAULTS.copy()
        try:
            saved = json.loads(CONFIG.read_text())
            self.settings.update({k: saved[k] for k in DEFAULTS if k in saved})
        except (OSError, ValueError, TypeError):
            pass
        if not voice_is_available(self.settings['voice'], self.settings):
            self.settings['voice'] = next((key for key, value in available_voices().items() if value[1] == 'kokoro'), DEFAULTS['voice'])
        if not languages.valid(self.settings['language']):
            self.settings['language'] = 'de'
        if self.settings['translate_to'] and (not languages.valid(self.settings['translate_to']) or self.settings['translate_to'] == self.settings['language']):
            self.settings['translate_to'] = ''
        try:
            self.settings['speed'] = min(2., max(.6, float(self.settings['speed'])))
        except (TypeError, ValueError):
            self.settings['speed'] = 1.
        self.online_token = saved_token(CONFIG.with_name('speech-credentials.json'), self.settings['online_endpoint']) if self.settings.get('remember_token') else ''
        self.translator_token = saved_token(CONFIG.with_name('translation-credentials.json'), self.settings['translator_endpoint']) if self.settings.get('remember_translator_token') else ''
        self.online_models = []
        self.provider_status = ''
        self.models_loading = False
        self.installing_kokoro = False
        self.install_task = None
        self.kokoro_checking = False
        self.kokoro_updates = {}
        self.enabled = self.paused = self.scanning = False
        self.status = 'Off'
        self.target = ''
        self.pending_window = None
        self.image_candidate = None
        self.ocr_image = None
        self.capture_stable = False
        self.target_title = ''
        self.target_class = ''
        self.last_text = self.candidate = ''
        self.last_error = ''
        self.queue = []
        self.epoch = 0
        self.custom_area = None
        self.overlay = HighlightOverlay(self, RUNTIME)
        self.highlight_queue = []
        self.audio_highlights = {}
        self.capture_area = None
        self.capture_window_geometry = None

        # Pipelined playback state
        self.player = None           # mpv Task currently playing
        self.playing_file = None     # Path to file currently playing
        self.tts_task = None         # Task generating the next chunk
        self.ready_file = None       # Path to .wav file that finished generating and waits to play

        self.menu = QMenu()
        self.toggle_action = self.menu.addAction('Start / stop reading')
        self.toggle_action.setCheckable(True)
        self.toggle_action.triggered.connect(lambda: self.set_enabled(not self.enabled, notify=True))
        self.start_action = self.menu.addAction('Start reading', lambda: self.set_enabled(True, notify=True) if not self.enabled else None)
        self.stop_action = self.menu.addAction('Stop reading', lambda: self.set_enabled(False, notify=True) if self.enabled else None)
        self.status_action = self.menu.addAction('Status: Off')
        self.status_action.setEnabled(False)
        self.menu.addSeparator()
        self.read_action = self.menu.addAction('Read active window again', lambda: self.read_again(repin=True))
        # Fixed label and always enabled: Launch & Bind binds entries by label and skips disabled ones.
        self.pause_action = self.menu.addAction('Pause / resume', self.pause)
        self.menu.addSeparator()
        self.select_area_action = self.menu.addAction('Select reading area…', self.select_area)
        self.clear_area_action = self.menu.addAction('Reset area (Full window)', self.clear_area)
        self.menu.addSeparator()
        # Choice submenus are rebuilt when their options change, so Launch & Bind
        # (which reads this menu over D-Bus) always lists the current choices.
        self.voice_menu = self.menu.addMenu('Voice')
        self.voice_actions = {}
        self.language_menu = self.menu.addMenu('Text language')
        self.translate_menu = self.menu.addMenu('Speak in (translation)')
        self.output_menu = self.menu.addMenu('Audio output')
        self.choice_signature = None
        self.menu.aboutToShow.connect(lambda: self.refresh_choice_menus(force=True))
        self.speed_menu = self.menu.addMenu('Reading speed')
        self.speed_group = QActionGroup(self)
        self.speed_actions = {}
        for rate in (.75, .9, 1., 1.1, 1.25, 1.5, 1.75, 2.):
            action = self.speed_menu.addAction(f'{rate:g}×')
            action.setCheckable(True)
            self.speed_group.addAction(action)
            action.triggered.connect(lambda checked=False, r=rate: self.set_speed(r))
            self.speed_actions[rate] = action
        self.menu.addAction('Settings…', self.show_settings)
        self.menu.addSeparator()
        self.menu.addAction('Quit Screen Narrator', self.app.quit)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scan)
        self.timer.setInterval(600)

        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.connection)
        self.clients = set()
        self.server.listen(str(RUNTIME / 'control.sock'))

        self.auto_configure()
        self.update()
        self.update()

    def is_speaking(self):
        return bool(self.player or self.tts_task or self.ready_file or self.queue)

    def save(self):
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        temp = CONFIG.with_suffix('.tmp')
        temp.write_text(json.dumps(getattr(self, 'preview_original', None) or self.settings, indent=2) + '\n')
        temp.replace(CONFIG)

    def readiness_checks(self):
        """What must be in place before reading can start. Each failed check names one
        primary fix the popup can run directly (first entry in `fixes`), plus alternatives:
        {label, command, args} runs a reader/setup command, {label, settings} applies
        settings, {label, panel} opens a popup page."""
        checks = []
        def check(ok, label, problem, fixes=()):
            checks.append(dict(ok=bool(ok), label=label, problem='' if ok else problem, fixes=[] if ok else list(fixes)))
        providers = dict(label='Choose another voice or provider…', panel='providers')
        code = self.voice_language()
        spoken = languages.name(code)
        if self.settings.get('provider', 'Local') == 'Online':
            check(self.settings.get('online_model') and self.settings.get('online_voice'), 'Speech server',
                  'The speech server needs a model and a voice.',
                  [dict(label='Finish speech server setup…', panel='providers')])
        else:
            voice_ok = voice_is_available(self.settings['voice'], self.settings) and \
                self.settings['voice'] in available_voices(code, self.settings)
            check(voice_ok, 'Voice · ' + spoken, 'There is no ' + spoken + ' voice yet.',
                  [dict(label='Install ' + spoken + ' voice (' + install_size(code) + ')', command='setup',
                        args=dict(language=code)), providers])
        text_code = self.settings['language']
        check(languages.ocr_language(text_code) in ocr_languages(), 'Text recognition · ' + languages.name(text_code),
              'Text recognition for ' + languages.name(text_code) + ' is not installed yet.',
              [dict(label='Install ' + languages.name(text_code) + ' text recognition', command='setup',
                    args=dict(language=text_code, backend_only=True))])
        check(self.settings.get('audio_output', 'auto') in {o['value'] for o in outputs()}, 'Audio output',
              'The selected speakers or headphones are not connected.',
              [dict(label='Use the system default output', settings=dict(audio_output='auto'))])
        checks.extend(self.extra_checks())
        return checks

    def auto_configure(self):
        """Fix what needs no decision: a translator for translation, an installed voice for the spoken language."""
        if self.settings.get('translate_to') and self.settings.get('translator') == 'llm' and not self.settings.get('translator_model'):
            if nllb_ready():
                self.settings['translator'] = 'nllb'
                self.save()
            elif translator_reachable(self.settings['translator_endpoint']) and not getattr(self, 'translator_models_loading', True):
                self.refresh_translator_models()  # picks the first model when it answers
        if self.settings.get('provider', 'Local') != 'Local':
            return
        choices = available_voices(self.voice_language(), self.settings)
        if choices and self.settings['voice'] not in choices:
            rank = {'kokoro': 0, 'piper': 1, 'qwen': 2}
            self.settings['voice'] = min(choices, key=lambda k: rank.get(choices[k][1], 3))
            self.save()

    def extra_checks(self):
        target = self.settings.get('translate_to')
        if not target:
            return []
        label = 'Translation · ' + languages.name(self.settings['language']) + ' → ' + languages.name(target)
        offline = dict(label='Use the offline translator', settings=dict(translator='nllb'))
        install = dict(label='Install offline translator (about 1.4 GB, non-commercial use)', command='install-translator')
        off = dict(label='Turn translation off', settings=dict(translate_to=''))
        server = dict(label='Use a translation server instead…', panel='translation')
        if self.settings.get('translator') == 'nllb':
            ok, problem, fixes = nllb_ready(), 'The offline translator is not installed yet.', [install, off, server]
        elif not self.settings.get('translator_model'):
            ok, problem = False, 'Translation is on, but no translator is set up yet.'
            fixes = [offline, off, server] if nllb_ready() else [install, off, server]
        else:
            ok = translator_reachable(self.settings['translator_endpoint'])
            problem = 'The translation server (' + self.settings['translator_endpoint'] + ') is not running.'
            fixes = ([offline] if nllb_ready() else []) + [off, server]
        return [dict(ok=ok, label=label, problem='' if ok else problem, fixes=[] if ok else fixes)]

    def voice_language(self):
        return speech_language(self.settings)

    def fill_choice_menu(self, menu, choices, current, handler):
        """Replace a submenu with checkable (value, label) choices; returns value -> action."""
        menu.clear()
        group = QActionGroup(menu)
        actions = {}
        for value, label in choices:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == current)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, v=value: handler(v))
            actions[value] = action
        return actions

    def refresh_choice_menus(self, force=False):
        voices = [(key, name) for key, (name, *_rest) in available_voices(self.voice_language(), self.settings).items()]
        outs = [(o['value'], o['label']) for o in outputs()]
        signature = (tuple(voices), tuple(outs), self.settings['voice'], self.settings['language'], self.settings['audio_output'],
                     self.settings.get('translate_to', ''))
        if signature == self.choice_signature and not force:
            return
        self.choice_signature = signature
        self.voice_actions = self.fill_choice_menu(self.voice_menu, voices, self.settings['voice'], self.set_voice)
        self.fill_choice_menu(self.language_menu, [(o['value'], o['label']) for o in languages.options()],
                              self.settings['language'], lambda v: self.menu_setting('language', v))
        self.fill_choice_menu(self.translate_menu, [('', 'Off · read in the text language')] +
                              [(o['value'], o['label']) for o in languages.options() if o['value'] != self.settings['language']],
                              self.settings.get('translate_to', ''), lambda v: self.menu_setting('translate_to', v))
        self.fill_choice_menu(self.output_menu, outs, self.settings['audio_output'], lambda v: self.menu_setting('audio_output', v))

    def menu_setting(self, key, value):
        try:
            self.configure_settings({key: value})
        except ValueError as error:
            self.fail(str(error))

    def update(self, status=None):
        if status:
            if status != self.status:
                print(f'Reader status: {self.status} -> {status}; target={self.target}',
                      file=sys.stderr, flush=True)
            self.status = status
        if hasattr(self, 'toggle_action'):
            self.toggle_action.setChecked(self.enabled)
        if hasattr(self, 'stop_action'):
            self.stop_action.setEnabled(True)
        self.status_action.setText('Status: ' + self.status)
        if hasattr(self, 'language_menu'):
            self.refresh_choice_menus()
        if self.settings['voice'] in self.voice_actions:
            self.voice_actions[self.settings['voice']].setChecked(True)
        for rate, action in self.speed_actions.items():
            action.setChecked(abs(rate - self.settings['speed']) < .01)

        if hasattr(self, 'clear_area_action'):
            has_area = (self.custom_area is not None) or bool(self.settings.get('kindle_area'))
            self.clear_area_action.setEnabled(has_area)

    def fail(self, message):
        print(message, file=sys.stderr, flush=True)
        self.update('Error — open the bar menu to retry')
        if message != self.last_error:
            # Qt tray messages set NeedsAttention and a themed attention icon.
            # The desktop shell crashed loading that icon after a Piper error.
            desktop_notify('Screen Narrator', message, level='error')
        self.last_error = message
        if getattr(self, 'testing_voice', False):
            self.set_enabled(False)
            self.update('Voice test failed: ' + message[:300])

    def stop_speech(self):
        self.kokoro_checking = False
        self.models_loading = False
        self.installing_kokoro = False
        self.epoch += 1
        self.overlay.show([])
        self.highlight_queue = []
        self.audio_highlights = {}
        self.mpv_command(['quit'])
        for task in list(self.speech_tasks):
            if task in self.tasks:
                task.cancel()
        self.speech_tasks.clear()
        for task in list(self.tasks):
            task.cancel()
        # Cancelled OCR callbacks cannot clear this flag themselves.
        self.scanning = False
        try:
            subprocess.run(['pkill', '-9', '-u', str(os.getuid()), '-f', str(RUNTIME / 'mpv.sock')],
                           stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        except Exception:
            pass
        self.player = None
        self.playing_file = None
        self.tts_task = None
        self.ready_file = None
        self.queue = []

    def set_enabled(self, enabled, notify=False):
        self.provider_status = ""
        if enabled and self.installing_kokoro:
            raise ValueError("Wait for Kokoro installation or cancel it before reading")
        if enabled and self.settings.get('provider', 'Local') == 'Online':
            endpoint_url(self.settings['online_endpoint'])
            if not self.settings.get('online_model') or not self.settings.get('online_voice'):
                raise ValueError('Choose an online speech model and voice')
        if enabled and self.settings.get('provider', 'Local') == 'Local' and not voice_is_available(self.settings['voice'], self.settings):
            raise ValueError('Selected voice is unavailable. Install its runtime and required models.')
        if enabled and not getattr(self, 'testing_voice', False):
            problems = [c['problem'] for c in self.readiness_checks() if not c['ok']]
            if problems:
                desktop_notify('Screen Narrator cannot start', problems[0], level='error')
                raise ValueError(problems[0])
        if getattr(self, 'preview_original', None) is not None:
            self.settings = self.preview_original
            self.online_token = self.preview_token
            self.preview_token = None
            self.preview_original = None
            self.preview_settings = None
        self.testing_voice = False
        was = self.enabled
        self.enabled = bool(enabled)
        self.paused = False
        self.stop_speech()
        for task in list(self.tasks):
            task.cancel()
        self.scanning = False
        self.target = self.last_text = self.candidate = ''
        self.pending_window = None
        self.image_candidate = self.ocr_image = None
        self.update('Looking for text…' if self.enabled else 'Off')
        if notify or was != self.enabled:
            msg = 'Screen Narrator: ON' if self.enabled else 'Screen Narrator: OFF'
            desktop_notify(msg, icon='audio-headphones', timeout=1500)
        if self.enabled:
            self.timer.start()
            QTimer.singleShot(350, self.scan)
        else:
            self.timer.stop()
            self.kokoro_worker.close()
            self.translation_worker.close()
            self.overlay.close()
            for name in ('window.png', 'ocr.png', 'ocr.txt', 'ocr.tsv', 'speech_0.txt', 'speech_0.wav', 'speech_1.txt', 'speech_1.wav'):
                (RUNTIME / name).unlink(missing_ok=True)

    def read_again(self, repin=False):
        print('Reader restart requested', file=sys.stderr, flush=True)
        if not self.enabled:
            self.set_enabled(True, notify=True)
        else:
            if repin:
                # Read the window that has the focus now instead of the pinned one.
                self.target = ''
            self.image_candidate = self.ocr_image = None
            self.stop_speech()
            self.paused = False
            self.last_text = self.candidate = ''
            self.update('Looking for text…')
            self.scan()

    def mpv_command(self, command):
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(.2)
                client.connect(str(RUNTIME / 'mpv.sock'))
                client.sendall((json.dumps({'command': command}) + '\n').encode())
        except OSError:
            pass

    def pause(self):
        if not self.enabled:
            return
        self.paused = not self.paused
        self.mpv_command(['set_property', 'pause', self.paused])
        self.update('Paused' if self.paused else 'Reading')
        if not self.paused:
            self.pump_pipeline()

    def set_voice(self, key):
        if not voice_is_available(key):
            raise ValueError('Voice runtime or required model is not installed')
        self.settings['voice'] = key
        self.save()
        self.update()
        if self.enabled:
            self.read_again()

    def set_speed(self, speed):
        self.settings['speed'] = max(.6, min(2., float(speed)))
        self.save()
        self.mpv_command(['set_property', 'speed', self.settings['speed']])
        self.update()

    def select_area(self):
        self.stop_speech()
        self.update('Select reading area with mouse…')
        desktop_notify('Screen Narrator', 'Drag a box around the reading area with your mouse (Esc to cancel)',
               icon='edit-select-all', timeout=4000)
        # 150ms delay lets the bar menu close before the extension takes the pointer
        QTimer.singleShot(150, lambda: Task(self, [*DESKTOP, 'select-area'], self.area_selected, timeout=95))

    def area_selected(self, code, out, err):
        if code or not out.strip():
            self.update('Looking for text…' if self.enabled else 'Off')
            desktop_notify('Screen Narrator', 'Area selection cancelled', icon='dialog-information', timeout=2000)
            return
        match = re.match(r'^(\d+),(\d+)\s+(\d+)x(\d+)$', out.strip())
        if not match:
            self.update('Looking for text…' if self.enabled else 'Off')
            return
        x, y, w, h = map(int, match.groups())
        if w < 20 or h < 20:
            self.update('Looking for text…' if self.enabled else 'Off')
            desktop_notify('Screen Narrator', 'Selected area was too small. Drag a box over the text to read.', level='warning',
                   icon='dialog-warning', timeout=2500)
            return

        # Always save the exact selected box for active reading across any application/browser!
        self.custom_area = (x, y, w, h)

        # In addition, check if this area was selected on the Kindle PWA to memorize relative proportions
        Task(self, [*DESKTOP, 'clients'], lambda c, o, e: self.apply_selected_area(x, y, w, h, o))

    def apply_selected_area(self, x, y, w, h, clients_json):
        cx = x + w / 2
        cy = y + h / 2
        kindle_win = None
        try:
            clients = json.loads(clients_json)
            for win in clients:
                cls = win.get('class', '').lower()
                title = win.get('title', '').lower()
                if 'kindle' in (title + cls) or 'klmgdcdnnefbfkpmkcmocagbihobefnh' in cls:
                    wx, wy = win['at']
                    ww, wh = win['size']
                    if wx <= cx < wx + ww and wy <= cy < wy + wh:
                        kindle_win = win
                        break
            if not kindle_win and self.is_kindle_target():
                for win in clients:
                    if win.get('address') == self.target:
                        kindle_win = win
                        break
        except Exception:
            pass

        if kindle_win:
            wx, wy = kindle_win['at']
            ww, wh = kindle_win['size']
            # Window-relative proportions (0.0 to 1.0)
            rx = max(0.0, (x - wx) / ww)
            ry = max(0.0, (y - wy) / wh)
            rw = min(1.0 - rx, w / ww)
            rh = min(1.0 - ry, h / wh)
            self.settings['kindle_area'] = [round(rx, 4), round(ry, 4), round(rw, 4), round(rh, 4)]
            self.save()
            msg = f'Reading area set & memorized for Kindle ({round(rw*100)}% × {round(rh*100)}%)'
        else:
            msg = f'Reading area set: {w}×{h} px'

        desktop_notify('Screen Narrator', msg, icon='edit-select-all', timeout=2000)
        self.update()
        if not self.enabled:
            self.set_enabled(True, notify=True)
        else:
            self.read_again()

    def clear_area(self):
        had_area = (self.custom_area is not None) or bool(self.settings.get('kindle_area'))
        self.custom_area = None
        if self.settings.get('kindle_area'):
            self.settings['kindle_area'] = None
            self.save()
        if had_area:
            desktop_notify('Screen Narrator', 'Reading area reset to default', icon='view-fullscreen', timeout=1500)
            self.update()
            if self.enabled:
                self.read_again()

    def pdf_keys(self):
        """(next-page key, scroll key) when the reading window is a known PDF viewer."""
        return viewer_keys(self.target_class, self.target_title)

    def is_kindle_target(self):
        title = (self.target_title or '').lower()
        cls = (self.target_class or '').lower()
        return 'kindle' in (title + cls) or 'klmgdcdnnefbfkpmkcmocagbihobefnh' in cls

    def scan(self):
        if getattr(self, 'testing_voice', False) or not self.enabled or self.paused or self.scanning or self.menu.isVisible():
            return
        if not self.settings['follow'] and self.last_text and self.status not in ('Waiting for the reading window', 'Turning to next page…'):
            if self.target:
                # No new pages, but closing the book still ends reading.
                self.scanning = True
                target = self.target
                Task(self, [*DESKTOP, 'window', target],
                     lambda code, out, err: self.check_book_open(code, out, err, target), timeout=5)
            return
        # Keep checking visible text during playback: manual page turns do not
        # change the window address, but invalidate queued and generated audio.
        self.scanning = True
        if self.target:
            # The window reading started in stays the book, wherever the focus goes.
            Task(self, [*DESKTOP, 'window', self.target], self.got_window, timeout=5)
        else:
            Task(self, [*DESKTOP, 'active-window'], self.got_window, timeout=5)

    def check_book_open(self, code, out, err, target=None):
        self.scanning = False
        if target is not None and target != self.target:
            # Another book was picked meanwhile (Read again): this answer is about the old one.
            return
        try:
            window = json.loads(out) if not code else None
            # The extension answers {} once the window is closed; a failed look-up or any
            # other answer is not a close.
            closed = window == {}
        except (ValueError, TypeError):
            closed = False
        if closed and self.enabled:
            self.book_closed()

    def book_closed(self):
        print(f'Reader target closed: {self.target}', file=sys.stderr, flush=True)
        self.scanning = False
        self.set_enabled(False)
        desktop_notify('Screen Narrator', 'Stopped: the reading window was closed', timeout=2000)

    def check_window_focus(self, code, out, err):
        if code:
            return
        try:
            window = json.loads(out)
            address = window.get('address', '')
            geometry = (window.get('at'), window.get('size'))
            if address == self.target and geometry != self.capture_window_geometry:
                # Existing focus poll also detects moves/resizes: old boxes are invalid.
                self.overlay.show([])
                self.audio_highlights.clear()
                self.highlight_queue = [[] for _ in self.queue]
            if address and address != self.target:
                # Use the same confirmed focus transition as normal OCR scans.
                self.scan()
        except Exception:
            pass

    def got_window(self, code, out, err):
        if code:
            self.scanning = False
            self.fail('Cannot access the active window: ' + err)
            return
        try:
            window = json.loads(out)
            if not well_formed_window(window):
                # The desktop service's answer is not a window entry: look again next time.
                self.scanning = False
                return
            address = window.get('address', '')
            if self.target and not window:
                # The book window was closed: reading it is over.
                self.book_closed()
                return
            if not address or window.get('pid') == os.getpid() or window.get('class') in NOT_BOOKS:
                self.scanning = False
                return
            x, y = window['at']
            width, height = window['size']
            if width < 60 or height < 60:
                self.scanning = False
                return
        except (ValueError, KeyError, TypeError):
            self.scanning = False
            return
        if window.get('shown') is False:
            # On another workspace or minimized the book stops drawing: keep reading what was
            # captured, look again when it is back.
            self.scanning = False
            return

        self.target_title = window.get('title', '')
        self.target_class = window.get('class', '')
        self.capture_window_geometry = (window['at'], window['size'])

        if self.target != address:
            # Switched window focus
            print(f'Reader target changed: {self.target} -> {address}; '
                  f'class={self.target_class}', file=sys.stderr, flush=True)
            self.stop_speech()
            self.target = address
            self.image_candidate = self.ocr_image = None
            self.last_text = self.candidate = ''
            self.update('Looking for text…')

        if self.custom_area:
            cx, cy, cw, ch = self.custom_area
            geom = f'{cx},{cy} {cw}x{ch}'
        else:
            is_kindle = self.is_kindle_target()
            if is_kindle and self.settings.get('kindle_area'):
                rx, ry, rw, rh = self.settings['kindle_area']
                cx = round(x + rx * width)
                cy = round(y + ry * height)
                cw = round(rw * width)
                ch = round(rh * height)
                # Kindle's first baseline can sit above a memorized crop after
                # toolbar/layout changes. Include a line of headroom so the
                # clipped-glyph filter does not discard the first book line.
                headroom = min(32, max(0, cy - y))
                cy -= headroom
                ch += headroom
                geom = f'{cx},{cy} {cw}x{ch}'
            elif is_kindle and self.settings['kindle_crop']:
                # Safe crop: only trim narrow top toolbar and bottom progress bar, preserving all text
                x += round(width * .04)
                y += round(height * .045)
                width = round(width * .92)
                height = round(height * .895)
            else:
                y += 32
                height -= 32
            if not (is_kindle and self.settings.get('kindle_area')):
                geom = f'{x},{y} {width}x{height}'
        self.capture_area = tuple(map(int, re.findall(r'-?\d+', geom)))
        self.scanning = True
        self.capture_highlight = (self.epoch, self.playing_file, self.overlay.last_payload)
        self.overlay.show([])
        epoch = self.epoch
        def capture():
            if self.epoch == epoch:
                # A chosen area is a part of the screen; otherwise the book window's own picture,
                # so windows over it do not end up in the text.
                if self.custom_area:
                    args = ['capture', geom]
                else:
                    args = ['capture-window', self.target, geom]
                Task(self, [*DESKTOP, *args, RUNTIME / 'window.png'], self.captured, timeout=5)
        if self.capture_highlight[2] and isinstance(self.capture_highlight[2], str) and json.loads(self.capture_highlight[2]).get('rectangles'):
            # Let the compositor present the hidden overlay before fingerprinting.
            QTimer.singleShot(35, capture)
        else:
            capture()

    def captured(self, code, out, err):
        epoch, playing_file, payload = self.capture_highlight
        if payload and epoch == self.epoch and playing_file == self.playing_file:
            highlight = json.loads(payload)
            self.overlay.show(highlight['rectangles'], highlight['target'])
        if code:
            self.scanning = False
            self.fail('Screen capture failed: ' + err)
            return
        crop = []
        self.pdf_cut_off = False
        if self.pdf_keys() and self.settings.get('pdf_page_area', True) and not self.custom_area:
            # Read only the page: no toolbar, thumbnails or neighbouring pages.
            try:
                page = find_page_in_image(RUNTIME / 'window.png')
            except Exception as error:
                print('PDF page detection failed: ' + str(error), file=sys.stderr, flush=True)
                page = None
            if page:
                px, py, pw, ph, self.pdf_cut_off = page
                ax, ay, aw, ah = self.capture_area
                scale = max(1e-6, self.image_width(RUNTIME / 'window.png') / max(1, aw))
                # No -normalize on a page: it would stretch the faint wallpaper that shows
                # through a slightly transparent window into dark blotches.
                crop = ['-crop', f'{pw}x{ph}+{px}+{py}', '+repage', '-colorspace', 'Gray']
                self.capture_area = (round(ax + px / scale), round(ay + py / scale), round(pw / scale), round(ph / scale))
        adjust = crop or ['-colorspace', 'Gray', '-normalize']
        Task(self, ['magick', RUNTIME / 'window.png', *adjust, '-strip', RUNTIME / 'ocr.png'], self.prepared, timeout=5)

    @staticmethod
    def image_width(path):
        from PySide6.QtGui import QImageReader
        return QImageReader(str(path)).size().width()

    def prepared(self, code, out, err):
        if code:
            self.scanning = False
            self.fail('Could not prepare screen text: ' + err)
            return
        try:
            digest = hashlib.sha256((RUNTIME / 'ocr.png').read_bytes()).digest()
        except OSError as error:
            self.scanning = False
            self.fail('Could not read captured image: ' + str(error))
            return
        if digest == self.ocr_image:
            self.scanning = False
            turned = getattr(self, 'pdf_turned_at', None)
            if turned and time.monotonic() - turned > 3 and not self.is_speaking():
                # A PDF page turn that changes nothing: the last page was read.
                self.pdf_turned_at = None
                self.page_turned_at = None
                self.turn_retries = 0
                self.set_enabled(False)
                self.update('End of document')
                return
            if getattr(self, 'status', '') == 'Turning to next page…' and not self.is_speaking():
                page_turned = getattr(self, 'page_turned_at', None)
                if page_turned and time.monotonic() - page_turned >= 1.2:
                    retries = getattr(self, 'turn_retries', 0)
                    if retries < 2:
                        self.turn_retries = retries + 1
                        self.page_turned_at = time.monotonic()
                        print(f'Reader retrying page turn ({self.turn_retries}/2): page unchanged',
                              file=sys.stderr, flush=True)
                        self.do_page_turn()
                        return
                    if time.monotonic() - page_turned >= 3:
                        self.page_turned_at = None
                        self.turn_retries = 0
                        self.set_enabled(False)
                        self.update('End of document')
                        return
            if self.status == 'Waiting for the reading window' and not self.is_speaking():
                self.on_page_finished()
            return
        if digest != self.image_candidate:
            self.image_candidate = digest
            self.scanning = False
            epoch = self.epoch
            QTimer.singleShot(100, lambda: self.scan() if self.epoch == epoch else None)
            return
        self.capture_stable = True
        args = ['tesseract', RUNTIME / 'ocr.png', RUNTIME / 'ocr', '--psm', '6']
        ocr_language = languages.ocr_language(self.settings['language'])
        if (DATA / 'tessdata' / (ocr_language + '.traineddata')).is_file():
            args += ['--tessdata-dir', DATA / 'tessdata']
        args += ['-l', ocr_language]
        # Speech and highlights share the same words from one recognition pass.
        args += ['-c', 'tessedit_create_txt=1']
        args += ['-c', 'tessedit_create_tsv=1']
        Task(self, args, self.recognized, timeout=15)

    def recognized(self, code, out, err):
        self.scanning = False
        if code:
            self.fail('OCR failed: ' + err)
            return
        try:
            raw, aligned_tsv = visible_ocr((RUNTIME / 'ocr.tsv').read_text())
            text = clean_text(raw)
        except (OSError, ValueError, KeyError, StopIteration) as error:
            self.fail('Could not read OCR output: ' + str(error))
            return
        turning = (getattr(self, 'pdf_turned_at', None) is not None or
                   getattr(self, 'page_turned_at', None) is not None or
                   getattr(self, 'status', '') == 'Turning to next page…')
        min_chars = 2 if turning and getattr(self, 'last_text', '') else 12
        if len(re.findall(r'\w', text)) < min_chars:
            if (turning and not self.is_speaking() and
                    getattr(self, 'image_candidate', None) not in (None, getattr(self, 'ocr_image', None))):
                # A blank or illustration page after a turn: move on to the next page.
                self.ocr_image = getattr(self, 'image_candidate', None)
                self.on_page_finished()
                return
            if not self.is_speaking():
                self.update('Waiting for readable text')
            return
        self.ocr_image = getattr(self, 'image_candidate', None)

        # Idle or waiting for next page. After a PDF page turn the page did change, even if
        # its text is nearly the same (slides that reveal content step by step).
        just_turned = getattr(self, 'pdf_turned_at', None) is not None
        if same_text(text, self.last_text, threshold=0.90) and not (just_turned and text != self.last_text):
            self.candidate = ''
            if just_turned and not self.is_speaking():
                # Same text on the new page (e.g. two blank pages): nothing to read, turn on.
                self.on_page_finished()
                return
            if getattr(self, 'status', '') == 'Turning to next page…' and not self.is_speaking():
                page_turned = getattr(self, 'page_turned_at', None)
                if page_turned and time.monotonic() - page_turned >= 1.2 and getattr(self, 'turn_retries', 0) < 2:
                    self.turn_retries = getattr(self, 'turn_retries', 0) + 1
                    self.page_turned_at = time.monotonic()
                    print(f'Reader retrying page turn ({self.turn_retries}/2): text unchanged',
                          file=sys.stderr, flush=True)
                    self.do_page_turn()
                return
            if getattr(self, 'status', '') == 'Waiting for the reading window' and not self.is_speaking():
                self.on_page_finished()
            return
        if not same_text(text, self.candidate, threshold=0.90) and not getattr(self, 'capture_stable', False):
            if self.is_speaking():
                # Stop stale speech as soon as a changed page is observed, then
                # require a second stable capture before reading the new page.
                self.stop_speech()
                self.update('Waiting for the page to settle…')
            self.candidate = text
            QTimer.singleShot(150, self.scan)
            return
        self.last_text = text
        self.pdf_turned_at = None
        self.page_turned_at = None
        self.turn_retries = 0
        self.candidate = ''
        self.stop_speech()
        self.queue = page_chunks(text)
        self.highlight_queue = [[] for _ in self.queue]
        if self.settings['highlight'] and self.capture_area:
            try:
                self.highlight_queue = chunk_rectangles(
                    aligned_tsv, self.queue, self.capture_area)
            except OSError:
                pass
        self.last_error = ''
        self.pump_pipeline()

    def speech_task(self, args, done, timeout=180, stdin_data=None):
        epoch = self.epoch
        def finished(code, out, err):
            self.speech_tasks.discard(task)
            if self.enabled and self.epoch == epoch:
                done(code, out, err)
        task = Task(self, args, finished, timeout, stdin_data=stdin_data)
        self.speech_tasks.add(task)
        return task

    def pump_pipeline(self):
        """Zero-gap audio pipeline: plays ready chunk and pre-generates next chunk concurrently."""
        if not self.enabled or self.paused:
            return

        # 1. Play ready chunk if player is idle
        if self.player is None:
            if self.ready_file and self.ready_file.exists():
                next_file = self.ready_file
                self.ready_file = None
                self.start_player(next_file)
            elif self.tts_task is None and self.queue:
                # First chunk of the page
                self.start_tts()
            elif not self.queue and self.tts_task is None and self.ready_file is None:
                # Page complete
                self.on_page_finished()
                return

        # 2. Pre-generate next chunk in parallel while playing
        if self.tts_task is None and self.ready_file is None and self.queue:
            self.start_tts()

    def start_tts(self):
        if not self.queue or not self.enabled or self.paused:
            return
        text = self.queue.pop(0)
        slot = '1' if self.playing_file == (RUNTIME / 'speech_0.wav') else '0'
        wav_file = RUNTIME / f'speech_{slot}.wav'
        self.audio_highlights[wav_file] = self.highlight_queue.pop(0) if self.highlight_queue else []
        txt_file = RUNTIME / f'speech_{slot}.txt'
        if self.settings.get('translate_to') and not getattr(self, 'testing_voice', False):
            self.translate_chunk(text, wav_file, txt_file)
        else:
            self.synthesize_chunk(text, wav_file, txt_file)

    def translation_request(self, text):
        return dict(text=text, settings=self.settings, token=self.translator_token)

    def translate_chunk(self, text, wav_file, txt_file):
        """Translate one chunk, then synthesize it; holds the TTS slot so prefetching still applies."""
        if self.player is None:
            self.update('Translating…')
        if self.translation_worker.pending is not None:
            self.translation_worker.close()  # A popup translation test yields to reading.
        epoch = self.epoch
        def on_done(code, out, err):
            self.tts_task = None
            if not self.enabled or self.epoch != epoch:
                return
            if code or not out.strip():
                self.queue.clear()
                self.fail('Translation failed. Check the translator under Translation, then press ▶ Start.\n' + (err or 'No text returned')[-500:])
                return
            self.synthesize_chunk(out, wav_file, txt_file)
        self.tts_task = self.translation_worker.request(self.translation_request(text), on_done)
        self.speech_tasks.add(self.tts_task)

    def synthesize_chunk(self, text, wav_file, txt_file):
        txt_file.write_text(text)

        _, engine, reference = VOICES[self.settings['voice']]
        online_payload = None
        custom_files = engine_files(self.settings, engine) if reference == 'custom' else None
        if reference.startswith('managed:'):
            managed = installed_settings(DATA, reference.split(':', 1)[1])
            custom_files = [Path(managed['piper_runner']), Path(managed['piper_model']), Path(managed['piper_config'])]
        if self.settings.get('provider', 'Local') == 'Online':
            args = [sys.executable, Path(__file__).with_name('online_provider.py')]
            online_payload = json.dumps({'settings': self.settings, 'token': self.online_token, 'input': str(txt_file), 'output': str(wav_file)})
        elif engine == 'kokoro':
            args = [HOME / '.local/bin/kindle-kokoro-tts',
                    '-m', reference,
                    '-i', txt_file, '-o', wav_file,
                    '-s', '1.0',  # Playback applies speed once, consistently across engines.
                    '-l', speech_language(self.settings)]
        elif engine == 'qwen':
            args = [custom_files[0] if custom_files else HOME / '.local/bin/llama-tts',
                    '-m', custom_files[1] if custom_files else QWEN_MODEL_DIR / 'Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf',
                    '-mm', custom_files[2] if custom_files else QWEN_MODEL_DIR / 'mmproj-Qwen3-TTS-12Hz-1.7B-Base-bf16.gguf',
                    '--tts-lang', speech_language(self.settings),
                    '--tts-speaker-file', custom_files[3] if custom_files else DATA / 'voices' / reference,
                    '-ngl', '99', '-c', '4096', '-n', '1536', '-t', '8', '--seed', '42',
                    '-f', txt_file, '-o', wav_file]
        else:
            args = [custom_files[0] if custom_files else DATA / 'venv/bin/piper',
                    '-m', custom_files[1] if custom_files else DATA / 'voices' / reference,
                    '--input-file', txt_file, '-f', wav_file]
            if custom_files:
                args += ['-c', custom_files[2]]

        if self.player is None:
            self.update('Preparing voice…')

        epoch = self.epoch
        def on_done(code, out, err):
            self.tts_task = None
            if not self.enabled or self.epoch != epoch:
                return
            if code:
                self.queue.clear()
                self.fail('Voice generation failed. Press ▶ Start to retry.\n' + err[-500:])
                return
            self.ready_file = wav_file
            self.pump_pipeline()

        if engine == 'kokoro' and online_payload is None:
            self.tts_task = self.kokoro_worker.request(
                dict(text=text, voice=reference, language=speech_language(self.settings),
                     output=str(wav_file)), on_done)
            self.speech_tasks.add(self.tts_task)
        else:
            self.tts_task = self.speech_task(args, on_done, stdin_data=online_payload)

    def start_player(self, wav_file):
        self.playing_file = wav_file
        try:
            device = playback_output(self.settings.get('audio_output', 'auto'))
        except ValueError as error:
            self.fail(str(error))
            self.ready_file = None
            self.queue.clear()
            return
        args = ['mpv', '--audio-device=' + device, '--no-video', '--no-terminal', '--audio-pitch-correction=yes',
                f'--speed={self.settings["speed"]}', f'--input-ipc-server={RUNTIME / "mpv.sock"}',
                '--pause=yes' if self.paused else '--pause=no', str(wav_file)]
        self.update('Paused' if self.paused else 'Reading')

        epoch = self.epoch
        def on_done(code, out, err):
            self.player = None
            self.playing_file = None
            if not self.enabled or self.epoch != epoch or code:
                self.overlay.show([])
                if code and self.enabled and self.epoch == epoch:
                    self.queue.clear()
                    self.fail('Audio playback failed: ' + err[-300:])
                return
            self.pump_pipeline()
            if self.player is None:
                # No next chunk ready: clear. A started one has already shown
                # its passage, so the highlight moves without a blank in between.
                self.overlay.show([])

        self.player = self.speech_task(args, on_done, timeout=600)
        self.overlay.show(self.audio_highlights.pop(wav_file, []) if self.settings['highlight'] else [], self.target)
        # While player is playing, trigger lookahead pre-generation of the next chunk
        self.pump_pipeline()

    def probe_provider(self, values):
        candidate = Reader.validated_settings(self, values)
        self.probed_settings = values.copy()
        self.probed_voices = [dict(value=k, label=v[0], engine=v[1])
                              for k, v in available_voices(speech_language(candidate), candidate).items()]

    def test_provider(self, values, token=None):
        if self.enabled:
            raise ValueError('Stop reading before testing a provider')
        if self.installing_kokoro or self.kokoro_checking:
            raise ValueError('Finish the model operation before testing a provider')
        candidate = Reader.validated_settings(self, values)
        self.verified_provider = None
        if token is not None and (not isinstance(token, str) or any(c in token for c in '\n\r') or len(token) > 16384):
            raise ValueError('Invalid provider token')
        original = self.settings
        original_token = self.online_token
        self.preview_token = original_token
        self.online_token = token if token else original_token if candidate['online_endpoint'] == original['online_endpoint'] else ''
        self.settings = candidate
        self.preview_token_digest = hashlib.sha256(self.online_token.encode()).hexdigest()
        try:
            self.preview_original = original
            self.preview_settings = values.copy()
            self.test_voice()
        except Exception:
            self.settings = original
            self.online_token = original_token
            self.preview_token = None
            self.preview_original = None
            self.preview_settings = None
            raise

    def use_provider(self, values, token=None, remember=False):
        if self.enabled:
            raise ValueError('Stop reading before activating a provider')
        if getattr(self, 'verified_provider', None) != values:
            raise ValueError('Test this provider voice before activating it')
        if token is not None and (not isinstance(token, str) or any(c in token for c in '\n\r') or len(token) > 16384):
            raise ValueError('Invalid provider token')
        if not isinstance(remember, bool):
            raise ValueError('Invalid token storage option')
        effective_token = token or (self.online_token if values.get('online_endpoint', self.settings['online_endpoint']) == self.settings['online_endpoint'] else '')
        if values.get('provider') == 'Online' and hashlib.sha256(effective_token.encode()).hexdigest() != self.verified_token_digest:
            raise ValueError('Test the provider again after changing its token')
        self.configure_settings(values)
        if values.get('provider') == 'Online':
            self.configure_token(token or self.online_token, remember)
        self.verified_provider = None
        self.provider_status = 'Speech provider activated'

    def test_voice(self):
        if self.enabled:
            raise ValueError('Stop reading before testing a voice')
        if getattr(self, 'installing_kokoro', False) or getattr(self, 'kokoro_checking', False):
            raise ValueError('Finish the model operation before testing a voice')
        if self.settings.get('provider') == 'Online':
            endpoint_url(self.settings['online_endpoint'])
            if not self.settings.get('online_model') or not self.settings.get('online_voice'):
                raise ValueError('Choose a speech model and voice first')
        elif not voice_is_available(self.settings['voice'], self.settings):
            raise ValueError('Set up a voice first')
        self.stop_speech()
        self.enabled = True
        self.paused = False
        self.testing_voice = True
        self.queue = [languages.sample(speech_language(self.settings))]
        self.highlight_queue = [[]]
        self.pump_pipeline()

    def on_page_finished(self):
        if getattr(self, 'testing_voice', False):
            self.verified_provider = getattr(self, 'preview_settings', None)
            self.verified_token_digest = getattr(self, 'preview_token_digest', None)
            self.testing_voice = False
            self.set_enabled(False)
            self.update('Voice test complete')
            return
        if self.settings.get('auto_page_turn', True) and (self.is_kindle_target() or self.pdf_keys()):
            for task in list(getattr(self, 'tasks', set()) - getattr(self, 'speech_tasks', set())):
                task.cancel()
            self.scanning = False
            self.candidate = ''
            if getattr(self, 'status', '') != 'Turning to next page…':
                self.turn_retries = 0
            self.update('Turning to next page…')
            epoch = self.epoch
            QTimer.singleShot(100, lambda: self.do_page_turn() if self.epoch == epoch else None)
        else:
            self.update('On — waiting for a new page')

    def do_page_turn(self):
        if not self.enabled or self.paused or not self.target:
            return
        # The desktop lends the book the focus for the key when it is in the background.
        keys = self.pdf_keys()
        # A page that continues below the window is scrolled first; otherwise next page.
        key = (keys[1] if getattr(self, 'pdf_cut_off', False) else keys[0]) if keys else 'Right'
        if not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{1,64}', str(self.target)):
            self.update('Waiting for the reading window')
            return
        Task(self, [*DESKTOP, 'send-key', self.target, key], self.page_turn_sent, timeout=3)

    def page_turn_sent(self, code, out, err):
        if not self.enabled or self.paused:
            return
        if code:
            # On another workspace or minimized: turn when it is back on screen.
            print('Reader page turn deferred: ' + err.strip(), file=sys.stderr, flush=True)
            self.update('Waiting for the reading window')
            return
        self.page_turned_at = time.monotonic()
        if self.pdf_keys():
            self.pdf_turned_at = self.page_turned_at
        # Scan early; the second matching OCR capture still confirms stability.
        epoch = self.epoch
        QTimer.singleShot(250, lambda: self.scan() if self.epoch == epoch else None)

    def show_settings(self):
        subprocess.Popen([*DESKTOP, 'open-settings'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def validated_settings(self, values):
        if not isinstance(values, dict):
            raise ValueError('Settings must be an object')
        allowed = {'voice', 'language', 'speed', 'follow', 'kindle_crop', 'pdf_page_area', 'auto_page_turn', 'highlight', 'provider', 'online_endpoint', 'online_model', 'online_voice', 'audio_output',
                   'translate_to', 'translator', 'translator_endpoint', 'translator_model'} | PATH_KEYS
        if set(values) - allowed:
            raise ValueError('Unknown setting')
        next_settings = self.settings.copy()
        for key, value in values.items():
            if key == 'audio_output':
                value = validate_output(value)
            if key == 'provider' and value not in ('Local', 'Online'):
                raise ValueError('Unknown speech provider')
            if key == 'online_endpoint':
                value = endpoint_url(value)
            if key in {'online_model', 'online_voice'} and (not isinstance(value, str) or len(value) > 256):
                raise ValueError('Enter a valid model or voice ID')
            if key == 'voice' and (not isinstance(value, str) or value not in VOICES):
                raise ValueError('Voice runtime or required model is not installed')
            if key == 'language' and not languages.valid(value):
                raise ValueError('Unknown language')
            if key == 'translate_to' and value != '' and not languages.valid(value):
                raise ValueError('Unknown translation language')
            if key == 'translator' and value not in ('llm', 'nllb'):
                raise ValueError('Unknown translator')
            if key == 'translator_endpoint':
                value = endpoint_url(value)
            if key == 'translator_model' and (not isinstance(value, str) or len(value) > 256 or any(c in value for c in '\n\r')):
                raise ValueError('Enter a valid translation model name')
            if key == 'speed':
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not .6 <= value <= 2.:
                    raise ValueError('Speed must be between 0.6 and 2')
            if key in {'follow', 'kindle_crop', 'pdf_page_area', 'auto_page_turn', 'highlight'} and not isinstance(value, bool):
                raise ValueError('Expected a boolean setting')
            if key in PATH_KEYS:
                value = normalize_path(value)
            next_settings[key] = value
        if next_settings.get('translate_to') == next_settings['language']:
            next_settings['translate_to'] = ''
        if speech_language(next_settings) != speech_language(self.settings) and next_settings['provider'] == 'Local':
            choices = available_voices(speech_language(next_settings), next_settings)
            if next_settings['voice'] not in choices:
                next_settings['voice'] = next((k for k, v in choices.items() if v[1] == 'kokoro'), next(iter(choices), DEFAULTS['voice']))
        if 'voice' in values and not voice_is_available(next_settings['voice'], next_settings):
            raise ValueError('Voice runtime or required model is not installed')
        if next_settings['provider'] == 'Online':
            endpoint_url(next_settings['online_endpoint'])
            if not next_settings.get('online_model') or not next_settings.get('online_voice'):
                if values.get('provider') == 'Online':
                    raise ValueError('Enter a speech model and voice before activating the provider')
        return next_settings

    def configure_settings(self, values):
        if getattr(self, 'preview_original', None) is not None:
            raise ValueError('Finish or stop the voice test before changing settings')
        next_settings = Reader.validated_settings(self, values)
        restart = any(next_settings[k] != self.settings[k] for k in ('voice', 'language', 'provider', 'online_endpoint', 'online_model', 'online_voice', 'audio_output',
                                                                      'translate_to', 'translator', 'translator_endpoint', 'translator_model', *PATH_KEYS))
        if next_settings['online_endpoint'] != self.settings['online_endpoint']:
            self.online_token = ''
            self.online_models = []
        if next_settings['translator_endpoint'] != self.settings['translator_endpoint']:
            self.translator_token = ''
            self.translator_models = []
        self.settings = next_settings
        self.auto_configure()
        self.verified_provider = None
        if not self.settings['highlight']:
            self.overlay.close()
        self.mpv_command(['set_property', 'speed', self.settings['speed']])
        self.save()
        self.update()
        if self.enabled and restart:
            self.read_again()

    def configure_token(self, token, remember):
        if not isinstance(token, str) or '\n' in token or '\r' in token or not isinstance(remember, bool):
            raise ValueError('Invalid token settings')
        store_token(CONFIG.with_name('speech-credentials.json'), self.settings['online_endpoint'], token, remember)
        self.online_token = token
        self.settings['remember_token'] = remember
        self.save()
        self.verified_provider = None
        self.provider_status = 'Token applied' if token else 'Token cleared'

    def refresh_online_models(self, endpoint=None, token=None):
        """The models of the active speech server, or of `endpoint` (a server being set up, with
        its `token`; the active token only goes to the active server)."""
        if self.enabled:
            raise ValueError("Stop reading before refreshing speech models")
        if token is not None and (not isinstance(token, str) or any(c in token for c in '\n\r') or len(token) > 16384):
            raise ValueError('Invalid provider token')
        settings = self.settings
        if endpoint:
            settings = dict(self.settings, online_endpoint=endpoint_url(endpoint))
        if not token:
            token = self.online_token if settings['online_endpoint'] == self.settings['online_endpoint'] else ''
        if self.models_loading:
            return
        self.models_loading = True
        self.provider_status = 'Refreshing online models…'
        def done(code, out, err):
            self.models_loading = False
            if code:
                self.provider_status = err.strip() or 'Model discovery failed; enter a model ID manually.'
                return
            try:
                self.online_models = json.loads(out)['models']
                self.provider_status = 'Models refreshed. Select a speech model; chat models cannot generate audio.'
            except (ValueError, KeyError, TypeError):
                self.provider_status = 'Cannot read provider model list.'
        Task(self, [sys.executable, Path(__file__).with_name('online_provider.py')], done, timeout=70,
             stdin_data=json.dumps({'action': 'models', 'settings': settings, 'token': token}))

    def kokoro_install_status(self):
        if self.installing_kokoro:
            try:
                return json.loads((RUNTIME / 'kokoro-install.json').read_text()).get('message', 'Installing Kokoro…')
            except (OSError, ValueError):
                return 'Installing Kokoro…'
        return self.provider_status

    def check_kokoro_updates(self, language, update=False):
        if language not in KOKORO:
            raise ValueError('Kokoro has no voice for this language')
        if self.enabled or self.installing_kokoro:
            raise ValueError('Stop reading before checking or updating models')
        if self.kokoro_checking:
            return
        if update and not self.kokoro_updates.get(language, {}).get('available'):
            raise ValueError('Check for model updates first')
        self.kokoro_checking = not update
        self.installing_kokoro = update
        self.provider_status = 'Updating Kokoro model…' if update else 'Checking official Kokoro model sources…'
        args = [sys.executable, Path(__file__).with_name('kokoro_updates.py'), '--language', language]
        if update:
            self.kokoro_worker.close()
            progress = RUNTIME / 'kokoro-install.json'
            progress.unlink(missing_ok=True)
            args += ['--update', '--progress', progress]
        def done(code, out, err):
            self.kokoro_checking = self.installing_kokoro = False
            self.install_task = None
            if code:
                self.provider_status = 'Model update failed: ' + err.strip()[-500:]
                return
            try:
                result = json.loads(out)
                self.kokoro_updates[language] = result
                self.provider_status = result['message']
            except (ValueError, KeyError, TypeError):
                self.provider_status = 'Cannot read model update result'
        self.install_task = Task(self, args, done, timeout=1800 if update else 90)

    def configure_translator_token(self, token, remember):
        if not isinstance(token, str) or '\n' in token or '\r' in token or len(token) > 16384 or not isinstance(remember, bool):
            raise ValueError('Invalid token settings')
        store_token(CONFIG.with_name('translation-credentials.json'), self.settings['translator_endpoint'], token, remember)
        self.translator_token = token
        self.settings['remember_translator_token'] = remember
        self.save()
        self.translation_status = 'Translation token applied' if token else 'Translation token cleared'

    def test_translation(self):
        """Translate the text language's sample sentence and show the result; no audio, no OCR."""
        if not self.settings.get('translate_to'):
            raise ValueError('Choose a language to translate into first')
        if self.translation_worker.pending is not None:
            raise ValueError('A translation is already running')
        if self.settings['translator'] == 'nllb' and not nllb_ready():
            raise ValueError('Install the offline translator first')
        sample = languages.sample(self.settings['language'])
        self.translation_status = 'Testing translation…'
        def done(code, out, err):
            self.translation_status = ('Translation works: ' + out.strip()[:300]) if not code else ('Translation test failed: ' + (err or 'no text')[-400:])
        self.translation_worker.request(self.translation_request(sample), done)

    def refresh_translator_models(self):
        if self.translator_models_loading:
            return
        self.translator_models_loading = True
        self.translation_status = 'Asking the translation server for its models…'
        def done(code, out, err):
            self.translator_models_loading = False
            if code:
                self.translation_status = err.strip()[-400:] or 'Model discovery failed; enter the model name manually.'
                return
            try:
                self.translator_models = json.loads(out)['models'][:200]
                if self.translator_models and not self.settings.get('translator_model'):
                    self.settings['translator_model'] = self.translator_models[0]
                    self.save()
                self.translation_status = 'Models refreshed. Choose a chat/instruct model.' if self.translator_models else 'The server lists no models; enter the model name manually.'
            except (ValueError, KeyError, TypeError):
                self.translation_status = 'Cannot read the server model list.'
        Task(self, [sys.executable, Path(__file__).with_name('translator.py')], done, timeout=30,
             stdin_data=json.dumps({'action': 'models', 'settings': self.settings, 'token': self.translator_token}))

    def install_translator(self):
        if self.enabled:
            raise ValueError('Stop reading before installing the offline translator')
        if self.installing_translator:
            return
        self.installing_translator = True
        progress = RUNTIME / 'translator-install.json'
        progress.unlink(missing_ok=True)
        def done(code, out, err):
            self.installing_translator = False
            self.translator_install_task = None
            if not code:
                self.settings['translator'] = 'nllb' if self.settings.get('translate_to') else self.settings['translator']
                self.save()
            self.translation_status = 'Offline translator installed. Choose Test translation.' if not code else (err.strip()[-500:] or 'Offline translator installation failed. Retry when your network is available.')
        self.translator_install_task = Task(self, [sys.executable, Path(__file__).with_name('install_nllb.py'), '--progress', progress], done, timeout=3600)

    def cancel_translator_install(self):
        if self.translator_install_task:
            self.translator_install_task.cancel()
            self.translator_install_task = None
        self.installing_translator = False
        self.translation_status = 'Offline translator installation cancelled; verified files are kept.'

    def translator_install_status(self):
        if self.installing_translator:
            try:
                return json.loads((RUNTIME / 'translator-install.json').read_text()).get('message', 'Installing offline translator…')
            except (OSError, ValueError):
                return 'Installing offline translator…'
        return self.translation_status

    def install_kokoro(self, language):
        if language not in KOKORO:
            raise ValueError('Kokoro has no voice for this language; use Piper')
        if self.enabled:
            raise ValueError('Stop reading before installing a speech model')
        if self.installing_kokoro:
            return
        self.installing_kokoro = True
        progress = RUNTIME / 'kokoro-install.json'
        progress.unlink(missing_ok=True)
        def done(code, out, err):
            self.installing_kokoro = False
            self.install_task = None
            if code:
                self.provider_status = err.strip()[-500:] or 'Kokoro installation failed. Retry when your network is available.'
                return
            self.provider_status = 'Kokoro installed for ' + languages.name(language)
            self.auto_configure()
        self.install_task = Task(self, [sys.executable, Path(__file__).with_name('install_kokoro.py'),
                                        '--language', language, '--progress', progress], done, timeout=1800)

    def cancel_kokoro_install(self):
        if self.install_task:
            self.install_task.cancel()
        self.install_task = None
        self.installing_kokoro = False
        self.provider_status = 'Kokoro installation cancelled'

    def connection(self):
        client = self.server.nextPendingConnection()
        self.clients.add(client)
        client.readyRead.connect(lambda: self.command(client))
        client.disconnected.connect(lambda: self.clients.discard(client))
        client.disconnected.connect(client.deleteLater)

    def command(self, client):
        # One request per line. "keep": true leaves the connection open for the next
        # request (the bar widget's reading-state watch); otherwise it closes after replying.
        while client.canReadLine():
            if not self.answer(client):
                client.disconnectFromServer()
                return

    def answer(self, client):
        """Reply to one request line; True keeps the connection open."""
        keep = False
        try:
            request = json.loads(bytes(client.readLine()))
            keep = request.get('keep') is True
            command = request['command']
            if command == 'watch':
                # Lightweight state for the bar icon, polled while the bar runs.
                client.write((json.dumps(dict(enabled=self.enabled, paused=self.paused, status=self.status)) + '\n').encode())
                client.flush()
                return keep
            if command == 'on': self.set_enabled(True, notify=True)
            elif command == 'off': self.set_enabled(False, notify=True)
            elif command == 'toggle': self.set_enabled(not self.enabled, notify=True)
            elif command == 'read': self.read_again(repin=True)
            elif command == 'test-voice': self.test_voice()
            elif command == 'probe-provider': self.probe_provider(request['settings'])
            elif command == 'test-provider': self.test_provider(request['settings'], request.get('token'))
            elif command == 'use-provider': self.use_provider(request['settings'], request.get('token'), request.get('remember_token', False))
            elif command == 'pause': self.pause()
            elif command == 'select-area': self.select_area()
            elif command == 'clear-area': self.clear_area()
            elif command == 'voice': self.set_voice(request['value'])
            elif command == 'speed': self.set_speed(request['value'])
            elif command == 'configure': self.configure_settings(request['settings'])
            elif command == 'configure-token': self.configure_token(request.get('token', ''), request.get('remember_token', False))
            elif command == 'online-models': self.refresh_online_models(request.get('endpoint'), request.get('token'))
            elif command == 'install-kokoro': self.install_kokoro(request.get('language', speech_language(self.settings)))
            elif command == 'check-kokoro-updates': self.check_kokoro_updates(request.get('language', self.settings['language']))
            elif command == 'update-kokoro': self.check_kokoro_updates(request.get('language', self.settings['language']), update=True)
            elif command == 'cancel-kokoro-install': self.cancel_kokoro_install()
            elif command == 'test-translation': self.test_translation()
            elif command == 'translator-models': self.refresh_translator_models()
            elif command == 'install-translator': self.install_translator()
            elif command == 'cancel-translator-install': self.cancel_translator_install()
            elif command == 'configure-translator-token': self.configure_translator_token(request.get('token', ''), request.get('remember_token', False))
            elif command == 'settings': self.show_settings()
            elif command == 'quit': QTimer.singleShot(100, self.app.quit)
            elif command != 'status': raise ValueError('Unknown command')
            response = dict(enabled=self.enabled, paused=self.paused, status=self.status,
                            custom_area=self.custom_area, testing_voice=self.testing_voice,
                            kokoro_checking=self.kokoro_checking, kokoro_updates=self.kokoro_updates,
                            engines={'piper': engine_ready(self.settings, 'piper'), 'qwen': engine_ready(self.settings, 'qwen')},
                            probed_settings=self.probed_settings, probed_voices=self.probed_voices,
                            piper_installations={lang: installed_settings(DATA, lang) for lang in PIPER if engine_ready(installed_settings(DATA, lang), 'piper')},
                            audio_outputs=outputs(), verified_provider=getattr(self, 'verified_provider', None),
                            settings=getattr(self, 'preview_original', None) or self.settings, key_ready=bool(self.online_token), online_models=self.online_models, models_loading=self.models_loading, provider_status=self.kokoro_install_status(), installing_kokoro=self.installing_kokoro, kokoro_languages={code: voice_is_available(next(k for k, v in VOICES.items() if v[1] == 'kokoro' and kokoro_voice_language(v[2]) == code), self.settings) for code in KOKORO}, languages=languages.options(), desktop_language=languages.default_language(),
                            translation_status=self.translator_install_status(), translator_models=self.translator_models,
                            translator_models_loading=self.translator_models_loading, installing_translator=self.installing_translator,
                            translation_testing=self.translation_worker.pending is not None and not self.enabled,
                            nllb_ready=nllb_ready(), translator_key_ready=bool(self.translator_token), translator_endpoints=TRANSLATOR_ENDPOINTS, notices=recent_notices(), checks=(checks := self.readiness_checks()), can_start=all(c['ok'] for c in checks), voices=[dict(value=k, label=v[0], engine=v[1]) for k, v in available_voices(speech_language(self.settings), self.settings).items()], window=self.target_title,
                            queued=len(self.queue), processes=[t.proc.processId() for t in self.speech_tasks])
        except (ValueError, KeyError, TypeError) as error:
            response = {'error': str(error)}
        client.write((json.dumps(response) + '\n').encode())
        client.flush()
        return keep

    def shutdown(self):
        self.set_enabled(False)
        self.server.close()


def main():
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    if len(sys.argv) > 1:
        # Small CLI for desktop launchers and lifecycle verification.
        if not (RUNTIME / 'control.sock').exists() and sys.argv[1] in ('settings', 'on', 'toggle', 'read', 'select-area', 'clear-area'):
            subprocess.run(['systemctl', '--user', 'start', 'ocrvox.service'], check=True)
            for _ in range(50):
                if (RUNTIME / 'control.sock').exists():
                    break
                time.sleep(.1)
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(5)
            try:
                client.connect(str(RUNTIME / 'control.sock'))
            except OSError:
                print('Screen Narrator is not running.', file=sys.stderr)
                return 1
            request = {'command': sys.argv[1]}
            if len(sys.argv) > 2:
                request['value'] = sys.argv[2]
            client.sendall((json.dumps(request) + '\n').encode())
            print(client.recv(65536).decode().strip())
        return 0
    app = QApplication([])
    app.setApplicationName('simple-reader')
    app.setApplicationDisplayName('Screen Narrator')
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(RUNTIME / 'reader.lock'))
    if not lock.tryLock(0):
        return 0
    QLocalServer.removeServer(str(RUNTIME / 'control.sock'))
    reader = Reader(app)
    app.aboutToQuit.connect(reader.shutdown)
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Python runs signal handlers only between its own steps: wake it now and then, so
    # `systemctl --user stop` ends the reader at once instead of after the stop timeout.
    wake = QTimer()
    wake.timeout.connect(lambda: None)
    wake.start(300)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
