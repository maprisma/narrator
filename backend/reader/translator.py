"""Optional translation before speech: a local or HTTPS LLM server, or offline NLLB-200."""
import contextlib
import json
import re
import sys
from pathlib import Path

from languages import NLLB, name
from online_provider import api_request

MODEL_DIR = Path.home() / '.local/share/kindle-reader/translation/nllb-200-distilled-1.3B'
MAX_INPUT = 4000
THINK = re.compile(r'<think>.*?</think>', re.S)
_NLLB = {}


def check_pair(source, target):
    if source not in NLLB or target not in NLLB or source == target:
        raise ValueError('Choose two different supported languages')


def translate_llm(endpoint, model, token, source, target, text):
    """Ask an OpenAI-compatible chat server (llama.cpp, LM Studio, Ollama, …) for a plain translation."""
    check_pair(source, target)
    if not isinstance(model, str) or not model.strip() or len(model) > 256:
        raise ValueError('Enter the translation model name')
    prompt = (f'Translate the user text from {name(source)} into {name(target)}. '
              'Reply with the translation only: no notes, quotes or explanations. '
              'Keep names, numbers and line breaks.')
    payload = {'model': model.strip(), 'temperature': 0, 'stream': False,
               'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': text}]}
    data = json.loads(api_request(endpoint, '/chat/completions', token, payload, limit=2 * 1024 * 1024, timeout=150))
    try:
        reply = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        raise ValueError('Translation server returned no chat reply. Use a chat model.') from None
    if not isinstance(reply, str):
        raise ValueError('Translation server returned no text')
    # Reasoning models (e.g. Qwen3 on llama.cpp) may prepend a think block.
    reply = THINK.sub('', reply).strip()
    if not reply:
        raise ValueError('Translation server returned an empty translation')
    return reply[:MAX_INPUT * 3]


def nllb_ready(folder=MODEL_DIR):
    return all((folder / item).is_file() for item in ('model.bin', 'config.json', 'shared_vocabulary.json', 'tokenizer.json'))


def translate_nllb(source, target, text, folder=MODEL_DIR):
    check_pair(source, target)
    if not nllb_ready(folder):
        raise ValueError('Install the offline translator first')
    import ctranslate2
    from tokenizers import Tokenizer
    key = str(folder)
    if key not in _NLLB:
        _NLLB.clear()
        _NLLB[key] = (ctranslate2.Translator(key, device='cpu', compute_type='int8'),
                      Tokenizer.from_file(str(folder / 'tokenizer.json')))
    model, tokenizer = _NLLB[key]
    lines, output = text.split('\n'), []
    batch = [line for line in lines if line.strip()]
    sources = [[NLLB[source]] + tokenizer.encode(line, add_special_tokens=False).tokens + ['</s>'] for line in batch]
    results = model.translate_batch(sources, target_prefix=[[NLLB[target]]] * len(sources),
                                    beam_size=2, max_decoding_length=512) if sources else []
    translated = iter(results)
    for line in lines:
        if not line.strip():
            output.append('')
            continue
        tokens = [t for t in next(translated).hypotheses[0] if t not in (NLLB[target], '</s>')]
        ids = [tokenizer.token_to_id(t) for t in tokens]
        output.append(tokenizer.decode([i for i in ids if i is not None]).strip())
    return '\n'.join(output).strip()


def translate(request):
    text = request.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_INPUT:
        raise ValueError('Translation input must contain 1–4000 characters')
    settings = request.get('settings') or {}
    source, target = settings.get('language'), settings.get('translate_to')
    if settings.get('translator') == 'nllb':
        return translate_nllb(source, target, text)
    return translate_llm(settings.get('translator_endpoint', ''), settings.get('translator_model', ''),
                         request.get('token') or '', source, target, text)


def serve():
    """Keep NLLB resident between chunks; stdin EOF releases it."""
    for line in sys.stdin:
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result = translate(json.loads(line))
            reply = {'code': 0, 'error': '', 'text': result}
        except Exception as error:  # Reported to the reader, never fatal for the worker.
            reply = {'code': 1, 'error': str(error)[-500:], 'text': ''}
        print(json.dumps(reply), flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        serve()
    else:
        try:
            payload = json.loads(sys.stdin.readline())
            if payload.get('action') == 'models':
                from online_provider import list_models
                print(json.dumps({'models': list_models(payload['settings']['translator_endpoint'], payload.get('token', ''))}))
            else:
                print(json.dumps({'text': translate(payload)}))
        except (ValueError, KeyError, OSError) as error:
            print(str(error), file=sys.stderr)
            sys.exit(1)
