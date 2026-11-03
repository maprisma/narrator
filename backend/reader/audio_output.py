"""Discover PulseAudio/PipeWire outputs without changing the desktop default."""
import json
import subprocess
import time

_cached = []
_checked = 0


def outputs(refresh=False):
    global _cached, _checked
    if not refresh and _cached and time.monotonic() - _checked < 10:
        return _cached
    result = [dict(value='auto', label='System default')]
    try:
        reply = subprocess.run(['pactl', '-f', 'json', 'list', 'sinks'],
                               capture_output=True, text=True, timeout=3, check=True)
        for sink in json.loads(reply.stdout):
            active = sink.get('active_port')
            if any(port.get('name') == active and port.get('availability') == 'not available' for port in sink.get('ports', [])):
                continue
            name = sink.get('name', '')
            if isinstance(name, str) and name and len(name) < 512 and not any(c in name for c in '\x00\n\r'):
                result.append(dict(value='pulse/' + name,
                                   label=str(sink.get('description') or name)))
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        pass
    _cached, _checked = result, time.monotonic()
    return result


def validate_output(value):
    if not isinstance(value, str) or value not in {entry['value'] for entry in outputs(refresh=True)}:
        raise ValueError('Audio output is unavailable. Choose System default or reconnect the device.')
    return value


def playback_output(value):
    # A disconnected headset must not cause playback to move to speakers silently.
    return validate_output(value or 'auto')
