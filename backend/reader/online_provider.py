"""OpenAI-compatible online speech, with private optional credentials."""
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def endpoint_url(endpoint):
    url = urllib.parse.urlsplit(str(endpoint).strip().rstrip('/'))
    if not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Enter a provider base URL without credentials, query or fragment')
    if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost', '::1'}):
        raise ValueError('Use HTTPS for remote providers')
    return urllib.parse.urlunsplit(url)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api_request(endpoint, path, token, payload=None, limit=32 * 1024 * 1024, timeout=60):
    base = endpoint_url(endpoint)
    if not base.endswith('/v1'):
        base += '/v1'
    headers = {'Content-Type': 'application/json'}
    if token:
        if '\n' in token or '\r' in token:
            raise ValueError('Invalid token')
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(base + path, headers=headers,
                                     data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('Provider response is too large')
            return data
    except urllib.error.HTTPError as error:
        raise ValueError(f'Server returned HTTP {error.code}. Check endpoint, token and model.') from None
    except urllib.error.URLError:
        raise ValueError('Cannot reach the server. Check that it is running, the endpoint and the network.') from None


def saved_token(path, endpoint):
    try:
        data = json.loads(Path(path).read_text())
        return str(data.get('token', '')) if data.get('endpoint') == endpoint_url(endpoint) else ''
    except (OSError, ValueError, TypeError):
        return ''


def store_token(path, endpoint, token, remember):
    path = Path(path)
    if not remember or not token:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.speech-token-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump({'endpoint': endpoint_url(endpoint), 'token': token}, output)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def list_models(endpoint, token):
    data = json.loads(api_request(endpoint, '/models', token, limit=2 * 1024 * 1024))
    return sorted({item['id'] for item in data.get('data', []) if isinstance(item, dict) and isinstance(item.get('id'), str)})


def synthesize(config, token, text, output):
    if not text.strip() or len(text) > 4096:
        raise ValueError('Speech input must contain 1–4096 characters')
    model, voice = config.get('online_model', '').strip(), config.get('online_voice', '').strip()
    if not model or not voice:
        raise ValueError('Choose an online speech model and voice')
    data = api_request(config['online_endpoint'], '/audio/speech', token,
                       {'model': model, 'voice': voice, 'input': text, 'response_format': 'wav', 'speed': 1.0})
    if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('Provider did not return WAV audio. Use a compatible speech endpoint.')
    Path(output).write_bytes(data)
    os.chmod(output, 0o600)


if __name__ == '__main__':
    try:
        payload = json.loads(sys.stdin.readline())
        config, token = payload['settings'], payload.get('token', '')
        if payload.get('action') == 'models':
            print(json.dumps({'models': list_models(config['online_endpoint'], token)}))
        else:
            synthesize(config, token, Path(payload['input']).read_text(), payload['output'])
    except (ValueError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
