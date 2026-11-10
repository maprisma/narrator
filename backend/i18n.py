"""UI language for the port's setup bridge; never changes the shared reader runtime."""
import json
import os
import re
from pathlib import Path
from translations_generated import CATALOGS


def system_language(env):
    locale = next((env[k] for k in ('LC_ALL', 'LC_MESSAGES', 'LANG') if env.get(k)), '')
    code = re.split(r'[_ .@-]', locale)[0].lower()
    return code if code in CATALOGS else 'en'


def language():
    try:
        config = Path(os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config'))
        code = json.loads((config / 'maprisma-narrator/settings.json').read_text()).get('interface_language')
        if code in CATALOGS:
            return code
    except (OSError, ValueError, TypeError):
        pass
    return system_language(os.environ)


def tr(text):
    return CATALOGS.get(language(), {}).get(text, text)


def trf(text, values):
    return re.sub(r'\{(\d+)\}', lambda m: str(values[int(m[1])]) if int(m[1]) < len(values) else m[0], tr(text))
