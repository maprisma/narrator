// Requests to the reader through backend/bridge.py: one JSON line in, the reader's full
// state (or {"error": ...}) as the last line out. Port of the extension's bridge.js.

import 'i18n.dart';
import 'dart:async';
import 'dart:convert';
import 'dart:io';

typedef Json = Map<String, dynamic>;

/// The bridge script: `$SCREEN_NARRATOR_BACKEND/bridge.py` when that variable names the
/// backend directory, otherwise `~/.local/share/maprisma-narrator/backend/bridge.py`.
String resolveBridgeScript([Map<String, String>? environment]) {
  final env = environment ?? Platform.environment;
  final backend = env['SCREEN_NARRATOR_BACKEND'];
  if (backend != null && backend.isNotEmpty) {
    return '${backend.replaceFirst(RegExp(r'/+$'), '')}/bridge.py';
  }
  final home = env['HOME'] ?? '';
  return '$home/.local/share/maprisma-narrator/backend/bridge.py';
}

/// The last line of the bridge's output as a JSON object, like bridge.js
/// (`JSON.parse(out.trim().split('\n').pop() || '{}')`). Failures become {error}.
Json parseBridgeOutput(String out) {
  final lines = out.trim().split('\n');
  final last = lines.last.trim();
  try {
    final value = jsonDecode(last.isEmpty ? '{}' : last);
    if (value is Map) return value.cast<String, dynamic>();
    return {'error': tr('Unexpected answer from the reader')};
  } on FormatException catch (error) {
    return {'error': error.message};
  }
}

class Bridge {
  Bridge({String? script, this.python = 'python3'}) : script = script ?? resolveBridgeScript();

  final String script;
  final String python;
  Future<void> _queue = Future.value();

  /// One request at a time, in order: the reader answers each with its full state.
  /// Resolves to that state; a failure resolves to {error}.
  Future<Json> request(Json payload) {
    final run = _queue.then((_) => _run(payload));
    _queue = run.then((_) {}, onError: (_) {});
    return run;
  }

  Future<Json> _run(Json payload) async {
    try {
      final process = await Process.start(python, [script]);
      final stdoutText = process.stdout.transform(utf8.decoder).join();
      final stderrDone = process.stderr.drain<void>();
      process.stdin.write('${jsonEncode(payload)}\n');
      await process.stdin.close();
      final out = await stdoutText;
      await stderrDone;
      await process.exitCode;
      return parseBridgeOutput(out);
    } catch (error) {
      return {'error': error is ProcessException ? error.message : error.toString()};
    }
  }
}

/// JavaScript truthiness, so nextStep reads the state exactly like bridge.js.
bool truthy(Object? value) {
  if (value == null || value == false) return false;
  if (value is num) return value != 0 && !value.isNaN;
  if (value is String) return value.isNotEmpty;
  return true;
}

class Step {
  const Step({required this.text, required this.label, required this.payload});

  final String? text;
  final String label;
  final Json? payload;

  @override
  String toString() => 'Step($text, $label, $payload)';
}

bool _hasItems(Object? list) => list is List && list.isNotEmpty;

/// The first thing standing in the way of reading, or null. Port of bridge.js nextStep.
Step? nextStep(Json state) {
  final settings = state['settings'];
  final language = (settings is Map ? settings['language'] : null) ?? 'en';
  if (truthy(state['setup_busy'])) {
    final message = state['setup_message'];
    return Step(
      text: truthy(message) ? '$message' : tr('Setting up…'),
      label: state['setup_phase'] == 'packages' ? '' : tr('Cancel'),
      payload: {'command': 'cancel-setup'},
    );
  }
  final missing = state['missing_packages'];
  if (state['backend_ready'] == false || _hasItems(missing)) {
    final payload = <String, dynamic>{'command': 'setup', 'language': language};
    if (['error', 'cancelled'].contains(state['setup_phase'])) {
      final message = state['setup_message'];
      return Step(text: message?.toString(), label: tr('Retry setup'), payload: payload);
    }
    final installs = _hasItems(missing) ? trf(' It installs {0}.', [(missing as List).join(', ')]) : '';
    return Step(
      text: tr('Maprisma Narrator needs its reader, a voice and text recognition.') + installs,
      label: tr('Set up automatically'),
      payload: payload,
    );
  }
  final checks = state['checks'];
  final failed = checks is List
      ? checks.whereType<Map>().cast<Map?>().firstWhere((c) => !truthy(c!['ok']), orElse: () => null)
      : null;
  if (failed == null || truthy(state['enabled'])) return null;
  final fixes = failed['fixes'];
  final fix = fixes is List
      ? fixes.whereType<Map>().cast<Map?>()
          .firstWhere((f) => truthy(f!['command']) || truthy(f['settings']), orElse: () => null)
      : null;
  final problem = failed['problem']?.toString();
  if (fix == null) return Step(text: problem, label: tr('Settings…'), payload: null);
  final Json payload;
  if (truthy(fix['command'])) {
    payload = {'command': fix['command']};
    final args = fix['args'];
    if (args is Map) payload.addAll(args.cast<String, dynamic>());
  } else {
    payload = {'command': 'configure', 'settings': fix['settings']};
  }
  return Step(text: problem, label: fix['label']?.toString() ?? '', payload: payload);
}
