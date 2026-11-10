"""Catalog coverage and generated-artifact checks, using only the standard library."""
import ast
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CODES = 'de fr es it pt nl pl'.split()


def source_keys():
    keys = set()
    paths = [*ROOT.glob('settings/lib/*.dart'), *ROOT.glob('applet/src/*.rs'),
             *ROOT.glob('tray/src/*.rs'), *ROOT.glob('desktop/src/*.rs'),
             ROOT / 'backend/bridge.py', ROOT / 'backend/setup_backend.py', ROOT / 'translations/i18n.rs']
    for path in paths:
        if path.name.endswith('.g.dart'):
            continue
        for match in re.finditer(r'''\btrf?\(\s*(['"])((?:\\.|(?!\1).)*)\1''', path.read_text()):
            # Dart interpolation is a dynamic message, not an English catalog key.
            if '$' not in match[2]:
                keys.add(ast.literal_eval(match[1] + match[2] + match[1]))
    return keys


class TranslationsTest(unittest.TestCase):
    def test_every_literal_key_and_desktop_field_in_every_language(self):
        keys = source_keys()
        self.assertGreater(len(keys), 100)
        for code in CODES:
            catalog = json.loads((ROOT / f'translations/{code}.json').read_text())
            extra = json.loads((ROOT / f'translations/extra/{code}.json').read_text())
            catalog.update(extra)
            self.assertFalse(keys - catalog.keys(), (code, keys - catalog.keys()))
            for key, value in catalog.items():
                self.assertTrue(value, (code, key))
                self.assertEqual(sorted(re.findall(r'\{\d+\}', key)), sorted(re.findall(r'\{\d+\}', value)), (code, key))
            for path in [*ROOT.glob('data/*.desktop'), ROOT / 'backend/maprisma-narrator.desktop']:
                lines = path.read_text().splitlines()
                for line in lines:
                    if line.startswith(('Name=', 'Comment=')):
                        field, key = line.split('=', 1)
                        self.assertIn(f'{field}[{code}]={catalog[key]}', lines)

    def test_generated_files_are_current(self):
        loader = importlib.machinery.SourceFileLoader('gen_translations', str(ROOT / 'tools/gen-translations'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        for path, expected in module.outputs().items():
            self.assertEqual((ROOT / path).read_text(), expected, path)

    def test_python_locale_precedence(self):
        sys.path.insert(0, str(ROOT / 'backend'))
        from i18n import system_language, trf
        for env, want in [({}, 'en'), ({'LANG': 'pl_PL.UTF-8'}, 'pl'),
                          ({'LC_ALL': '', 'LC_MESSAGES': 'fr_FR.UTF-8', 'LANG': 'de'}, 'fr'),
                          ({'LC_ALL': 'xx_YY', 'LANG': 'de'}, 'en'),
                          ({'LC_ALL': 'C.UTF-8', 'LANG': 'de'}, 'en'),
                          ({'LC_ALL': 'pt_BR.UTF-8', 'LC_MESSAGES': 'fr'}, 'pt')]:
            self.assertEqual(system_language(env), want)
        self.assertEqual(trf('{0} / {1}', ['{1}', 'data']), '{1} / data')


if __name__ == '__main__':
    unittest.main()
