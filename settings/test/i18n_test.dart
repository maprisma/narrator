import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/i18n.dart';
import 'package:maprisma_narrator/main.dart';

import 'page_test.dart' show FakeBridge;

void main() {
  setUp(() => interfaceLanguage.value = 'en');
  tearDown(() => interfaceLanguage.value = 'auto');

  test('system locale precedence and unknown-language fallback', () {
    expect(systemLanguage({}), 'en');
    expect(systemLanguage({'LANG': 'pl_PL.UTF-8'}), 'pl');
    expect(
      systemLanguage({
        'LC_ALL': '',
        'LC_MESSAGES': 'fr_FR.UTF-8',
        'LANG': 'de',
      }),
      'fr',
    );
    expect(systemLanguage({'LC_ALL': 'xx_YY', 'LANG': 'de'}), 'en');
    expect(systemLanguage({'LC_ALL': 'C.UTF-8', 'LANG': 'de'}), 'en');
    expect(
      systemLanguage({'LC_ALL': 'pt_BR.UTF-8', 'LC_MESSAGES': 'fr'}),
      'pt',
    );
    for (final code in languageNames.keys) {
      expect(systemLanguage({'LANG': '${code}_XX.UTF-8'}), code);
    }
  });

  test(
    'persists language independently of reader settings, preserving other keys',
    () {
      final dir = Directory.systemTemp.createTempSync('narrator-i18n-');
      addTearDown(() => dir.deleteSync(recursive: true));
      final file = File('${dir.path}/settings.json')
        ..writeAsStringSync('{"other":42}');
      setInterfaceLanguage('de', settingsFile: file);
      expect(readLanguage(settingsFile: file), 'de');
      expect(file.readAsStringSync(), contains('"other":42'));
      expect(tr('Start'), 'Starten');
      expect(tr('untranslated'), 'untranslated');
      expect(
        message('Install English voice (80 MB)'),
        'Stimme für English installieren (80 MB)',
      );
      expect(
        message('There is no English voice yet.'),
        'Es gibt noch keine Stimme für English.',
      );
      expect(message('Model XYZ'), 'Model XYZ');
      expect(trf('Reading: {0}', ['{1}']), 'Vorlesen: {1}');
      setInterfaceLanguage('auto', settingsFile: file);
      expect(readLanguage(settingsFile: file), 'auto');
      file.writeAsStringSync('{"interface_language":"xx"}');
      expect(readLanguage(settingsFile: file), 'auto');
      file.writeAsStringSync('broken');
      expect(readLanguage(settingsFile: file), 'auto');
    },
  );

  testWidgets('open settings rebuild immediately after language change', (
    tester,
  ) async {
    final bridge = FakeBridge({
      'status': 'Off',
      'settings': {'language': 'en'},
    });
    await tester.pumpWidget(SettingsApp(bridge: bridge));
    await tester.pump();
    expect(find.text('Language'), findsWidgets);
    interfaceLanguage.value = 'de';
    await tester.pump();
    expect(find.text('Sprache'), findsWidgets);
    expect(find.text('Language'), findsNothing);
    expect(bridge.sent.every((p) => p['command'] == 'status'), isTrue);
    await tester.pumpWidget(const SizedBox());
  });
}
