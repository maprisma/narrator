import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/desktop_theme.dart';
import 'package:maprisma_narrator/look.dart';

void main() {
  test('corner sizes', () {
    for (final (r, control, small, pill) in [(12.0, 8.0, 4.0, 999.0), (6.0, 6.0, 4.0, 999.0), (2.0, 2.0, 2.0, 999.0), (0.0, 0.0, 0.0, 0.0), (20.0, 8.0, 4.0, 999.0)]) {
      final c = Corners(r);
      expect([c.radius, c.control, c.small, c.pill], [r, control, small, pill]);
    }
    expect(cornerRadius('slight'), 6);
    expect(cornerRadius('rounded'), 12);
    expect(cornerRadius('square'), 0);
    expect(cornerRadius('desktop'), isNull);
    expect(cornerRadius('bogus'), isNull);
  });

  test("COSMIC's corner_radii: the medium radius", () {
    const ron = '(\n    radius_0: (0.0, 0.0, 0.0, 0.0),\n    radius_xs: (4.0, 4.0, 4.0, 4.0),\n'
        '    radius_s: (8.0, 8.0, 8.0, 8.0),\n    radius_m: (16.0, 16.0, 16.0, 16.0),\n)';
    expect(parseRadiusM(ron), 16);
    expect(parseRadiusM('radius_m: (2.0, 2.0, 2.0, 2.0)'), 2);
    expect(parseRadiusM('nothing'), isNull);
    final tmp = Directory.systemTemp.createTempSync('look-test-');
    addTearDown(() => tmp.deleteSync(recursive: true));
    final env = {'HOME': tmp.path, 'XDG_CONFIG_HOME': tmp.path};
    expect(desktopRadius(Brightness.dark, env), 16); // no COSMIC theme: libcosmic's 16
    File('${tmp.path}/cosmic/com.system76.CosmicTheme.Dark/v1/corner_radii')
      ..createSync(recursive: true)
      ..writeAsStringSync(ron);
    File('${tmp.path}/cosmic/com.system76.CosmicTheme.Light/v1/corner_radii')
      ..createSync(recursive: true)
      ..writeAsStringSync('(radius_s: (2.0, 2.0, 2.0, 2.0), radius_m: (2.0, 2.0, 2.0, 2.0))');
    expect(desktopRadius(Brightness.dark, env), 16);
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
    // Like the desktop: Material's corners untouched.
    expect(DesktopTheme.theme(Brightness.dark, null).extension<CornerSizes>(), isNull);
    expect(DesktopTheme.theme(Brightness.dark, null, radius: 0).extension<CornerSizes>()!.radius, 0);
  });
}
