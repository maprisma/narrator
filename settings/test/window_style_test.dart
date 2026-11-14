import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:maprisma_narrator/window_style.dart';

void main() {
  late Directory tmp;
  late Map<String, String> env;
  setUp(() {
    tmp = Directory.systemTemp.createTempSync('window-style-');
    env = {'HOME': tmp.path, 'XDG_CONFIG_HOME': '${tmp.path}/config', 'XDG_STATE_HOME': '${tmp.path}/state'};
  });
  tearDown(() => tmp.deleteSync(recursive: true));

  test('unset, unknown, oversized or non-file settings mean Solid', () async {
    expect(resolvedWindowStyle(env), 'solid');
    File(windowsFilePath(env))
      ..createSync(recursive: true)
      ..writeAsStringSync('{"style": "rainbow"}');
    expect(chosenWindowStyle(env), 'solid');
    File(windowsFilePath(env)).writeAsStringSync('{"style": "glassy", "pad": "${'x' * 5000}"}');
    expect(chosenWindowStyle(env), 'solid');
    File(windowsFilePath(env)).deleteSync();
    Directory(windowsFilePath(env)).createSync();
    expect(chosenWindowStyle(env), 'solid');
  });

  test('a chosen style and its alpha; writing keeps the other keys', () async {
    await writeWindowsSetting('theme_blur', true, env);
    await writeWindowsSetting('style', 'transparent', env);
    expect(readWindowsFile(env), {'theme_blur': true, 'style': 'transparent'});
    expect(windowAlpha(resolvedWindowStyle(env)), transparentAlpha);
    await writeWindowsSetting('style', 'glassy', env);
    expect(windowAlpha(resolvedWindowStyle(env)), glassyAlpha);
  });

  test('Follow the desktop: Omarchy toggles, else the theme blur flag', () async {
    await writeWindowsSetting('style', 'follow', env);
    expect(resolvedWindowStyle(env), 'solid');                     // no Omarchy, no blur
    await writeWindowsSetting('theme_blur', true, env);
    expect(resolvedWindowStyle(env), 'glassy');
    final toggles = Directory('${env['XDG_STATE_HOME']}/omarchy/toggles/hypr')..createSync(recursive: true);
    expect(resolvedWindowStyle(env), 'transparent');               // Omarchy: its default style
    File('${toggles.path}/window-glassy.lua').writeAsStringSync('');
    expect(resolvedWindowStyle(env), 'glassy');
    File('${toggles.path}/window-opaque.lua').writeAsStringSync('');
    expect(resolvedWindowStyle(env), 'solid');                     // opaque wins, as in Omarchy
  });
}
