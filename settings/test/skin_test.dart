import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/app_theme.dart';
import 'package:maprisma_narrator/bridge.dart';
import 'package:maprisma_narrator/look.dart';
import 'package:maprisma_narrator/main.dart';
import 'package:maprisma_narrator/skin.dart';
import 'package:maprisma_ui/window_style.dart';

class _Bridge extends Bridge {
  _Bridge() : super(script: '/dev/null');
  @override
  Future<Json> request(Json payload) async => {
    'status': 'Ready',
    'backend_ready': true,
    'settings': <String, dynamic>{},
  };
}

void main() {
  test('order, normalization and exact palettes', () {
    expect(appSkins, [
      'native',
      'synthwave',
      'cozy',
      'terminal',
      'disco',
      'zen',
    ]);
    expect(normalizeSkin(null), 'native');
    expect(normalizeSkin('unknown'), 'native');
    expect(skinStyle('native'), isNull);
    final expected = [
      (
        'synthwave',
        0xffff2e93,
        0xff00e5ff,
        0xff3a1259,
        0xff130924,
        0xfff4eaff,
        1.5,
      ),
      (
        'cozy',
        0xfff09a36,
        0xffe0822a,
        0xff593012,
        0xff21150e,
        0xfff5e8d6,
        1.25,
      ),
      (
        'terminal',
        0xff2ce868,
        0xff22c55e,
        0xff0d381a,
        0xff09130b,
        0xffd2fce0,
        1.25,
      ),
      (
        'disco',
        0xffd946ef,
        0xfffacc15,
        0xff4c1666,
        0xff1c0c2b,
        0xfff8ecff,
        1.5,
      ),
      ('zen', 0xff52b798, 0xff64c2a4, 0xff1e3832, 0xff141d1c, 0xffe2f0ec, 1.0),
    ];
    for (final (name, accent, border, bg, window, foreground, width)
        in expected) {
      final style = skinStyle(name)!;
      expect(
        [
          style.accent.toARGB32(),
          style.borderTint.toARGB32(),
          style.bgTint.toARGB32(),
          style.windowBg.toARGB32(),
          style.foreground.toARGB32(),
          style.borderWidth,
        ],
        [accent, border, bg, window, foreground, width],
      );
      expect(style.toDesktopColors(), {
        'accent': colorHex(style.accent),
        'background': colorHex(style.windowBg),
        'foreground': colorHex(style.foreground),
      });
      expect(skinLabel(name, (s) => s), isNotEmpty);
    }
  });

  test('theme, extensions and window transparency compose', () {
    final base = appTheme(
      Brightness.dark,
      const {},
      6,
      fonts: const {'ui': 'Example', 'mono': 'Mono'},
    );
    expect(identical(applySkinToTheme(base, 'native'), base), isTrue);
    for (final name in appSkins.skip(1)) {
      final style = skinStyle(name)!;
      final theme = applySkinToTheme(base, name, radius: 6);
      expect(theme.colorScheme.primary, style.accent);
      expect(theme.colorScheme.surface, style.windowBg);
      expect(theme.colorScheme.onSurface, style.foreground);
      expect(theme.extension<Corners>()!.radius, 6);
      expect(theme.extension<AppFonts>()!.mono, 'Mono');
      expect(theme.extension<StateColors>(), isNotNull);
      expect(
        (theme.cardTheme.shape as RoundedRectangleBorder).side.width,
        style.borderWidth,
      );
      final glass = withWindowAlpha(theme, .6);
      expect(glass.scaffoldBackgroundColor.a, closeTo(.6, .001));
      expect(glass.cardTheme.color!.a, closeTo(.8, .001));
      expect(glass.dialogTheme.backgroundColor!.a, 1);
      expect(glass.popupMenuTheme.color!.a, 1);
      expect(glass.menuTheme.style!.backgroundColor!.resolve({})!.a, 1);
    }
  });

  test('settings preserve other keys and omit Native', () {
    final dir = Directory.systemTemp.createTempSync('skin-test-');
    addTearDown(() => dir.deleteSync(recursive: true));
    final file = File('${dir.path}/settings.json')
      ..writeAsStringSync('{"language":"de","corners":"rounded"}');
    saveLook(skin: 'disco', file: file);
    expect(readLook(file).skin, 'disco');
    expect(jsonDecode(file.readAsStringSync()), {
      'language': 'de',
      'corners': 'rounded',
      'skin': 'disco',
    });
    saveLook(skin: 'native', file: file);
    expect(jsonDecode(file.readAsStringSync()), {
      'language': 'de',
      'corners': 'rounded',
    });
    expect(LookSettings.fromJson({'skin': 'bogus'}).skin, 'native');
  });

  testWidgets('selecting a skin saves and applies it live', (tester) async {
    final dir = Directory.systemTemp.createTempSync('skin-widget-');
    addTearDown(() => dir.deleteSync(recursive: true));
    final original = lookSettingsFile;
    lookSettingsFile = () => File('${dir.path}/settings.json');
    look.value = const LookSettings();
    addTearDown(() {
      lookSettingsFile = original;
      look.value = const LookSettings();
    });
    tester.view.physicalSize = const Size(900, 2200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(SettingsApp(bridge: _Bridge()));
    await tester.pump();
    expect(find.text('App skin'), findsWidgets);
    final button = find.byWidgetPredicate(
      (w) =>
          w is OutlinedButton &&
          w.child is Row &&
          find
              .descendant(of: find.byWidget(w), matching: find.text('Native'))
              .evaluate()
              .isNotEmpty,
    );
    await tester.tap(button.first);
    await tester.pump();
    await tester.tap(find.text('Disco').last);
    await tester.pump();
    await tester.pump();
    expect(look.value.skin, 'disco');
    expect(jsonDecode(lookSettingsFile().readAsStringSync())['skin'], 'disco');
    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.themeMode, ThemeMode.dark);
    expect(app.darkTheme!.colorScheme.primary, skinStyle('disco')!.accent);
    await tester.pumpWidget(const SizedBox());
  });
}
