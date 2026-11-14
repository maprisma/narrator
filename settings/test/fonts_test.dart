import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/app_theme.dart';

void main() {
  test('the desktop\'s interface font is the theme\'s; its monospace font is monoFont\'s', () {
    final t = appTheme(Brightness.dark, const {}, 12, fonts: const {'ui': 'Noto Sans', 'mono': 'Hack'});
    expect(t.textTheme.bodyMedium!.fontFamily, 'Noto Sans');
    expect(t.extension<AppFonts>()!.mono, 'Hack');
    final none = appTheme(Brightness.dark, const {}, 12);
    expect(none.extension<AppFonts>()!.mono, isNull);
    expect(fontFamily(const {'ui': '  '}, 'ui'), isNull);
  });

  testWidgets('monoFont: the desktop\'s, else monospace', (tester) async {
    late String a, b;
    await tester.pumpWidget(MaterialApp(
      theme: appTheme(Brightness.dark, const {}, 12, fonts: const {'mono': 'Hack'}),
      home: Builder(builder: (c) => Text(a = monoFont(c))),
    ));
    await tester.pumpWidget(MaterialApp(key: UniqueKey(), home: Builder(builder: (c) => Text(b = monoFont(c)))));
    expect((a, b), ('Hack', 'monospace'));
  });
}
