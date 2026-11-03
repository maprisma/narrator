import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:screen_narrator_settings/bridge.dart';
import 'package:screen_narrator_settings/main.dart';

class FakeBridge extends Bridge {
  FakeBridge(this.state) : super(script: '/dev/null');
  final Json state;
  final sent = <Json>[];

  @override
  Future<Json> request(Json payload) async {
    sent.add(payload);
    return state;
  }
}

void main() {
  testWidgets('renders every group from a full state', (tester) async {
    tester.view.physicalSize = const Size(640, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final bridge = FakeBridge({
      'status': 'Off',
      'enabled': false,
      'backend_ready': true,
      'setup_busy': false,
      'missing_packages': [],
      'checks': [
        {'ok': false, 'problem': 'No voice yet', 'fixes': [{'label': 'Install voice', 'command': 'install-kokoro'}]},
      ],
      'notices': [{'title': 'Voice', 'text': 'failed'}],
      'languages': [
        {'value': 'en', 'label': 'English'},
        {'value': 'de', 'label': 'German · Deutsch'},
      ],
      'voices': [{'value': 'kokoro-martin', 'label': 'Martin · Kokoro'}],
      'audio_outputs': [{'value': 'auto', 'label': 'Automatic'}],
      'kokoro_languages': {'de': true, 'en': true},
      'kokoro_updates': {'de': {'available': true, 'message': 'A newer model is available'}},
      'translator_models': ['qwen2.5'],
      'key_ready': true,
      'translator_key_ready': true,
      'online_models': ['tts-1'],
      'custom_area': [0, 0, 800, 600],
      'settings': {
        'language': 'en',
        'speed': 1.0,
        'voice': 'kokoro-martin',
        'audio_output': 'auto',
        'translate_to': 'de',
        'translator': 'llm',
        'translator_endpoint': 'http://127.0.0.1:8080/v1',
        'translator_model': 'qwen2.5',
        'provider': 'Local',
      },
    });
    await tester.pumpWidget(SettingsApp(bridge: bridge));
    await tester.pump();
    for (final text in ['Install voice', 'Last problem', 'Reading', 'Selected area (800×600 px)', 'Voice',
        'Kokoro model updates', 'Update', 'Qwen voice', 'Speech server', 'Models on the server', 'Translation',
        'Translator', 'Test translation', 'Saved token of the server in use']) {
      expect(find.text(text), findsWidgets, reason: text);
    }
    await tester.tap(find.text('Install voice'));
    await tester.pump();
    expect(bridge.sent.last, {'command': 'install-kokoro'});
    await tester.tap(find.text('Select…'));
    await tester.pump();
    expect(bridge.sent.last, {'command': 'select-area'});
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('status group offers Start, Pause and Stop when ready', (tester) async {
    tester.view.physicalSize = const Size(640, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final bridge = FakeBridge({
      'status': 'Ready',
      'enabled': false,
      'backend_ready': true,
      'setup_busy': false,
      'missing_packages': [],
      'checks': [
        {'ok': true},
      ],
      'settings': {'language': 'en', 'speed': 1.0, 'provider': 'Local'},
    });
    await tester.pumpWidget(SettingsApp(bridge: bridge));
    await tester.pump();
    expect(find.text('Start'), findsOneWidget);
    await tester.tap(find.text('Start'));
    await tester.pump();
    expect(bridge.sent.last, {'command': 'on'});
    await tester.pumpWidget(const SizedBox());
  });
}
