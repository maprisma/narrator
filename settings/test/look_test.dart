import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/app_theme.dart';
import 'package:maprisma_narrator/look.dart';

void main() {
  test('corner sizes', () {
    for (final (r, control, small, pill) in [(12.0, 8.0, 4.0, 999.0), (6.0, 6.0, 4.0, 999.0), (2.0, 2.0, 2.0, 999.0), (0.0, 0.0, 0.0, 0.0), (20.0, 8.0, 4.0, 999.0)]) {
      final c = Corners(r);
      expect([c.radius, c.control, c.small, c.pill], [r, control, small, pill]);
    }
    expect(cornerRadius('slight', 15), 6);
    expect(cornerRadius('rounded', 15), 12);
    expect(cornerRadius('square', 15), 0);
    // Like the desktop: its windows' rounding, 12 when unknown.
    expect(cornerRadius('desktop', 15), 15);
    expect(cornerRadius('desktop', null), 12);
    expect(cornerRadius('bogus', 0), 0);
    expect(cornerLabel('desktop', 15), 'Like the desktop (15 px)');
    expect(cornerLabel('desktop', null), 'Like the desktop (12 px)');
  });

  test('settings: defaults, and saving keeps the other keys', () {
    expect(LookSettings.fromJson(null), const LookSettings());
    expect(LookSettings.fromJson({'screenshot_key': 'no', 'corners': 'round'}), const LookSettings());
    expect(LookSettings.fromJson({'screenshot_key': false, 'corners': 'square'}),
        const LookSettings(screenshotKey: false, corners: 'square'));
    final tmp = Directory.systemTemp.createTempSync('look-test-');
    addTearDown(() => tmp.deleteSync(recursive: true));
    final file = File('${tmp.path}/maprisma-narrator/settings.json');
    expect(readLook(file), const LookSettings());
    saveLook(corners: 'slight', file: file);
    file.writeAsStringSync(jsonEncode({...jsonDecode(file.readAsStringSync()) as Map, 'interface_language': 'de'}));
    saveLook(screenshotKey: false, file: file);
    saveLook(corners: 'bogus', file: file);
    expect(jsonDecode(file.readAsStringSync()), {'corners': 'slight', 'interface_language': 'de', 'screenshot_key': false});
    expect(readLook(file), const LookSettings(screenshotKey: false, corners: 'slight'));
    expect(look.value, const LookSettings(screenshotKey: false, corners: 'slight'));
  });

  test('the theme carries the corners', () {
    final theme = appTheme(Brightness.dark, const {}, 6);
    expect((theme.cardTheme.shape as RoundedRectangleBorder).borderRadius, BorderRadius.circular(6));
    expect((theme.filledButtonTheme.style!.shape!.resolve({}) as RoundedRectangleBorder).borderRadius,
        BorderRadius.circular(6));
    expect((theme.checkboxTheme.shape as RoundedRectangleBorder).borderRadius, BorderRadius.circular(4));
    final square = appTheme(Brightness.dark, const {}, 0);
    expect((square.dialogTheme.shape as RoundedRectangleBorder).borderRadius, BorderRadius.zero);
    expect(theme.extension<Corners>()!.radius, 6);
  });
}
