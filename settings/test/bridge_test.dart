import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/bridge.dart';

void main() {
  group('nextStep', () {
    test('ready and nothing failing gives null', () {
      expect(nextStep({'backend_ready': true, 'checks': [{'ok': true}]}), isNull);
      expect(nextStep({}), isNull);
    });

    test('setup busy offers Cancel, except during packages', () {
      var step = nextStep({'setup_busy': true, 'setup_message': 'Installing voice…', 'setup_phase': 'voice'})!;
      expect(step.text, 'Installing voice…');
      expect(step.label, 'Cancel');
      expect(step.payload, {'command': 'cancel-setup'});
      step = nextStep({'setup_busy': true, 'setup_message': '', 'setup_phase': 'packages'})!;
      expect(step.text, 'Setting up…');
      expect(step.label, '');
    });

    test('backend not ready offers setup with the language and missing packages', () {
      final step = nextStep({
        'backend_ready': false,
        'missing_packages': ['grim', 'slurp'],
        'settings': {'language': 'de'},
        'setup_phase': 'idle',
      })!;
      expect(step.label, 'Set up automatically');
      expect(step.text, 'Maprisma Narrator needs its reader, a voice and text recognition. It installs grim, slurp.');
      expect(step.payload, {'command': 'setup', 'language': 'de'});
    });

    test('missing packages alone also need setup; default language en', () {
      final step = nextStep({'backend_ready': true, 'missing_packages': ['grim']})!;
      expect(step.payload, {'command': 'setup', 'language': 'en'});
      final none = nextStep({'backend_ready': false, 'missing_packages': []})!;
      expect(none.text, 'Maprisma Narrator needs its reader, a voice and text recognition.');
    });

    test('failed setup offers Retry setup', () {
      final step = nextStep({'backend_ready': false, 'setup_phase': 'error', 'setup_message': 'Boom'})!;
      expect(step.label, 'Retry setup');
      expect(step.text, 'Boom');
    });

    test('a failed check with a command fix spreads its args', () {
      final step = nextStep({
        'backend_ready': true,
        'checks': [
          {'ok': true},
          {
            'ok': false,
            'problem': 'No voice',
            'fixes': [
              {'label': 'Nothing'},
              {'label': 'Install', 'command': 'install-kokoro', 'args': {'language': 'fr'}},
            ],
          },
        ],
      })!;
      expect(step.text, 'No voice');
      expect(step.label, 'Install');
      expect(step.payload, {'command': 'install-kokoro', 'language': 'fr'});
    });

    test('a failed check with a settings fix configures', () {
      final step = nextStep({
        'checks': [
          {'ok': false, 'problem': 'P', 'fixes': [{'label': 'Turn off', 'settings': {'translate_to': ''}}]},
        ],
      })!;
      expect(step.payload, {'command': 'configure', 'settings': {'translate_to': ''}});
    });

    test('a failed check without a fix opens settings; enabled hides checks', () {
      final step = nextStep({'checks': [{'ok': false, 'problem': 'P', 'fixes': []}]})!;
      expect(step.label, 'Settings…');
      expect(step.payload, isNull);
      expect(nextStep({'enabled': true, 'checks': [{'ok': false, 'problem': 'P'}]}), isNull);
    });
  });

  group('parseBridgeOutput', () {
    test('uses the last line', () {
      expect(parseBridgeOutput('noise\n{"a": 1}\n{"status": "ok"}\n'), {'status': 'ok'});
    });
    test('empty output is an empty state', () {
      expect(parseBridgeOutput(''), <String, dynamic>{});
    });
    test('errors pass through and bad JSON becomes an error', () {
      expect(parseBridgeOutput('{"error": "Unknown command"}'), {'error': 'Unknown command'});
      expect(parseBridgeOutput('Traceback…').containsKey('error'), isTrue);
      expect(parseBridgeOutput('[1]').containsKey('error'), isTrue);
    });
  });

  test('resolveBridgeScript', () {
    expect(resolveBridgeScript({'SCREEN_NARRATOR_BACKEND': '/opt/b/', 'HOME': '/h'}), '/opt/b/bridge.py');
    expect(resolveBridgeScript({'HOME': '/h'}), '/h/.local/share/maprisma-narrator/backend/bridge.py');
  });

  test('Bridge sends one JSON line and serializes requests', () async {
    final dir = await Directory.systemTemp.createTemp('bridge_test');
    addTearDown(() => dir.delete(recursive: true));
    final script = File('${dir.path}/bridge.py');
    final log = '${dir.path}/log';
    await script.writeAsString('''
import json, sys, time
payload = json.loads(sys.stdin.readline())
open(${'"'}$log${'"'}, "a").write(payload["command"] + " start\\n")
time.sleep(0.1)
open(${'"'}$log${'"'}, "a").write(payload["command"] + " end\\n")
print("debug line")
print(json.dumps({"echo": payload}))
''');
    final bridge = Bridge(script: script.path);
    final results = await Future.wait([
      bridge.request({'command': 'status'}),
      bridge.request({'command': 'configure', 'settings': {'speed': 1.2}}),
    ]);
    expect(results[0], {'echo': {'command': 'status'}});
    expect(results[1], {'echo': {'command': 'configure', 'settings': {'speed': 1.2}}});
    expect(await File(log).readAsLines(), ['status start', 'status end', 'configure start', 'configure end']);
    final missing = await Bridge(script: script.path, python: '/nonexistent/python3').request({'command': 'status'});
    expect(missing.containsKey('error'), isTrue);
  });
}
