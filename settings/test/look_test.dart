import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/look.dart';

void main() {
  test('corner sizes', () {
    for (final (r, control, small, pill) in [(12.0, 8.0, 4.0, 999.0), (6.0, 6.0, 4.0, 999.0), (2.0, 2.0, 2.0, 999.0), (0.0, 0.0, 0.0, 0.0), (20.0, 8.0, 4.0, 999.0)]) {
      final c = Corners(r);
      expect([c.radius, c.control, c.small, c.pill], [r, control, small, pill]);
    }
    expect(cornerRadius('slight', 20), 6);
    expect(cornerRadius('rounded', 20), 12);
    expect(cornerRadius('square', 20), 0);
    expect(cornerRadius('desktop', 20), 20);
    expect(cornerRadius('bogus', 20), 20);
  });

  test("COSMIC's corner_radii: radius_s, window = s + 4 from 4 on", () {
    const ron = '(\n    radius_0: (0.0, 0.0, 0.0, 0.0),\n    radius_xs: (4.0, 4.0, 4.0, 4.0),\n'
        '    radius_s: (8.0, 8.0, 8.0, 8.0),\n    radius_m: (16.0, 16.0, 16.0, 16.0),\n)';
    expect(parseRadiusS(ron), 8);
    expect(parseRadiusS('radius_s: (2.0, 2.0, 2.0, 2.0)'), 2);
    expect(parseRadiusS('nothing'), isNull);
    expect(windowRadius(8), 12);
    expect(windowRadius(2), 2);
    final tmp = Directory.systemTemp.createTempSync('look-test-');
    addTearDown(() => tmp.deleteSync(recursive: true));
    final env = {'HOME': tmp.path, 'XDG_CONFIG_HOME': tmp.path};
    expect(desktopRadius(Brightness.dark, env), 12); // no COSMIC theme: 12
    File('${tmp.path}/cosmic/com.system76.CosmicTheme.Dark/v1/corner_radii')
      ..createSync(recursive: true)
      ..writeAsStringSync(ron);
    File('${tmp.path}/cosmic/com.system76.CosmicTheme.Light/v1/corner_radii')
      ..createSync(recursive: true)
      ..writeAsStringSync('(radius_s: (2.0, 2.0, 2.0, 2.0))');
    expect(desktopRadius(Brightness.dark, env), 12);
    expect(desktopRadius(Brightness.light, env), 2);
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
    final theme = withCorners(ThemeData(), const Corners(6));
    expect((theme.cardTheme.shape as RoundedRectangleBorder).borderRadius, BorderRadius.circular(6));
    expect((theme.filledButtonTheme.style!.shape!.resolve({}) as RoundedRectangleBorder).borderRadius,
        BorderRadius.circular(6));
    expect((theme.checkboxTheme.shape as RoundedRectangleBorder).borderRadius, BorderRadius.circular(4));
    final square = withCorners(ThemeData(), const Corners(0));
    expect((square.dialogTheme.shape as RoundedRectangleBorder).borderRadius, BorderRadius.zero);
    expect(theme.extension<CornerSizes>()!.radius, 6);
  });
}
