// The desktop's palette and corners from fake session files (never the real ones), and the
// window's theme built from it.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/app_theme.dart';
import 'package:maprisma_narrator/bridge.dart';
import 'package:maprisma_narrator/desktop_look.dart';
import 'package:maprisma_narrator/look.dart';
import 'package:maprisma_narrator/main.dart';

const scheme = {
  'colours': {
    'primary': 'E78A4E', 'surface': '231a13', 'onSurface': 'e8d5b7', 'outline': '9c8a78',
    'surfaceContainerHighest': '3c2f25', 'error': 'ea6962', 'yellow': 'd8a657', 'peach': 'e78a4e',
    'green': 'a9b665', 'onPrimary': 'zzzzzz',
  },
};

class _Bridge extends Bridge {
  _Bridge() : super(script: '/nonexistent');
  @override
  Future<Json> request(Json payload) async => {};
}

void main() {
  late Directory tmp;
  late Map<String, String> env;
  setUp(() {
    tmp = Directory.systemTemp.createTempSync('desktop-look-test-');
    env = {'HOME': tmp.path};
    // The window's own settings (corners): none, never the user's file.
    lookSettingsFile = () => File('${tmp.path}/interface.json');
  });
  tearDown(() => tmp.deleteSync(recursive: true));

  File file(String path) => File('${tmp.path}/$path')..createSync(recursive: true);

  test('Hyprland: Maprisma Shell scheme.json and hyprctl rounding', () {
    env['XDG_CURRENT_DESKTOP'] = 'Hyprland';
    expect(readDesktopLook(env: env, root: tmp.path), const DesktopLook(desktop: 'hyprland'));
    file('.local/state/maprisma-shell/scheme.json').writeAsStringSync(jsonEncode(scheme));
    final look = readDesktopLook(env: env, root: tmp.path, hyprRounding: 15);
    expect(look.colors, {
      'accent': '#e78a4e', 'background': '#231a13', 'foreground': '#e8d5b7', 'muted': '#9c8a78',
      'selection': '#3c2f25', 'red': '#ea6962', 'yellow': '#d8a657', 'orange': '#e78a4e', 'green': '#a9b665',
    });
    expect(look.rounding, 15);
    expect(look.isDark, isTrue);
    // XDG_STATE_HOME moves it.
    env['XDG_STATE_HOME'] = '${tmp.path}/elsewhere';
    expect(readDesktopLook(env: env, root: tmp.path).colors, isEmpty);
    expect(shellColors('not json'), isEmpty);
    expect(shellColors('{"colours": {"surface": "#231a13"}}'), isEmpty);
    expect(shellColors('{"colours": {"background": "FAFAFA"}}'), {'background': '#fafafa'});
  });

  test("hyprctl's answer", () {
    expect(parseHyprRounding('{"option": "decoration:rounding", "int": 15, "set": true}'), 15);
    expect(parseHyprRounding('{"int": 99}'), isNull);
    expect(parseHyprRounding('{"float": 1.5}'), isNull);
    expect(parseHyprRounding('garbage'), isNull);
  });

  test('KDE: kdeglobals, missing keys from the fallback', () {
    env['XDG_CURRENT_DESKTOP'] = 'KDE';
    file('.config/kdeglobals').writeAsStringSync('''
[Colors:Window]
BackgroundNormal=35,26,19
ForegroundNormal=232,213,183
ForegroundInactive=156,138,120

[Colors:View]
ForegroundNegative=234,105,98
DecorationFocus=1,2,3

[General]
AccentColor=231,138,78
''');
    final look = readDesktopLook(env: env, root: tmp.path);
    expect(look.rounding, 8);
    expect(look.colors['accent'], '#e78a4e'); // AccentColor before DecorationFocus
    expect(look.colors['background'], '#231a13');
    expect(look.colors['foreground'], '#e8d5b7');
    expect(look.colors['muted'], '#9c8a78');
    expect(look.colors['red'], '#ea6962');
    expect(look.colors['green'], darkFallback['green']);
    expect(kdeColors('')['accent'], '#3daee9');
    expect(kdeColors('[Colors:Window]\nBackgroundNormal=250,250,250')['foreground'], lightFallback['foreground']);
  });

  test('COSMIC: the theme of the mode, radius_s as the rounding', () {
    env['XDG_CURRENT_DESKTOP'] = 'COSMIC';
    file('.config/cosmic/com.system76.CosmicTheme.Mode/v1/is_dark').writeAsStringSync('false');
    const dir = '.config/cosmic/com.system76.CosmicTheme.Light/v1';
    file('$dir/accent').writeAsStringSync('(base: (red: 1.0, green: 0.5, blue: 0.0, alpha: 1.0), hover: (red: 0.0, green: 0.0, blue: 0.0))');
    file('$dir/background').writeAsStringSync('(base: (red: 1.0, green: 1.0, blue: 1.0, alpha: 1.0), on: (red: 0.0, green: 0.0, blue: 0.0, alpha: 1.0))');
    file('$dir/corner_radii').writeAsStringSync('(radius_0: (0.0, 0.0, 0.0, 0.0), radius_s: (8.0, 8.0, 8.0, 8.0), radius_m: (16.0, 16.0, 16.0, 16.0))');
    final look = readDesktopLook(env: env, root: tmp.path);
    expect(look.colors['accent'], '#ff8000');
    expect(look.colors['background'], '#ffffff');
    expect(look.colors['foreground'], '#000000');
    expect(look.rounding, 8);
    expect(look.isDark, isFalse);
  });

  test('other desktops: nothing', () {
    env['XDG_CURRENT_DESKTOP'] = 'GNOME';
    expect(readDesktopLook(env: env, root: tmp.path), const DesktopLook());
  });

  test('without XDG_CURRENT_DESKTOP: the session decides', () {
    expect(desktopName({'XDG_SESSION_DESKTOP': 'KDE', 'DESKTOP_SESSION': 'plasma'}), 'kde');
    expect(desktopName({'DESKTOP_SESSION': '/usr/share/wayland-sessions/plasmawayland.desktop'}), 'kde');
    expect(desktopName({'XDG_SESSION_DESKTOP': 'COSMIC'}), 'cosmic');
    expect(desktopName({'DESKTOP_SESSION': 'hyprland-uwsm'}), 'hyprland');
    expect(desktopName({'HYPRLAND_INSTANCE_SIGNATURE': 'abc'}), 'hyprland');
    expect(desktopName({'KDE_FULL_SESSION': 'true'}), 'kde');
    expect(desktopName({'XDG_CURRENT_DESKTOP': '', 'DESKTOP_SESSION': 'gnome'}), 'other');
    // a set XDG_CURRENT_DESKTOP still wins
    expect(desktopName({'XDG_CURRENT_DESKTOP': 'GNOME', 'KDE_FULL_SESSION': 'true'}), 'other');
  });

  test('the watcher: files every 5 s, hyprctl every 30 s', () async {
    env['XDG_CURRENT_DESKTOP'] = 'Hyprland';
    var asked = 0;
    final watcher = DesktopLookWatcher(env: env, root: tmp.path, hyprRounding: () async => 10 + asked++);
    final t0 = DateTime(2026);
    expect((await watcher.read(now: t0)).rounding, 10);
    final schemeFile = file('.local/state/maprisma-shell/scheme.json')..writeAsStringSync(jsonEncode(scheme));
    expect((await watcher.read(now: t0.add(const Duration(seconds: 2)))).colors, isEmpty);
    final fresh = await watcher.read(now: t0.add(const Duration(seconds: 5)));
    expect(fresh.colors['background'], '#231a13');
    expect(fresh.rounding, 10);
    expect(asked, 1);
    schemeFile.deleteSync();
    expect((await watcher.read(now: t0.add(const Duration(seconds: 30)))).rounding, 11);
    expect(asked, 2);
  });

  testWidgets("the window takes the desktop's palette and corners", (tester) async {
    desktopLook.value = const DesktopLook(
      desktop: 'hyprland',
      colors: {'background': '#231a13', 'accent': '#e78a4e', 'foreground': '#e8d5b7', 'green': '#a9b665'},
      rounding: 15,
    );
    addTearDown(() => desktopLook.value = const DesktopLook());
    await tester.pumpWidget(SettingsApp(bridge: _Bridge()));
    final context = tester.element(find.byType(Scaffold).first);
    final theme = Theme.of(context);
    expect(theme.colorScheme.surface, const Color(0xff231a13));
    expect(theme.colorScheme.primary, const Color(0xffe78a4e));
    expect(theme.colorScheme.onSurface, const Color(0xffe8d5b7));
    expect(theme.colorScheme.onPrimary, Colors.white); // luminance .36: white text on the accent
    expect(theme.brightness, Brightness.dark);
    expect(stateColors(context).ok, const Color(0xffa9b665));
    look.value = readLook();
    await tester.pump();
    expect(Theme.of(context).extension<Corners>()!.radius, 15); // Corners: Like the desktop
    // A new scheme: the window follows.
    desktopLook.value = const DesktopLook(desktop: 'hyprland', colors: {'background': '#fafafa', 'accent': '#3584e4'}, rounding: 0);
    await tester.pump();
    await tester.pump(const Duration(seconds: 1)); // the theme's change animation
    final light = Theme.of(tester.element(find.byType(Scaffold).first));
    expect(light.colorScheme.surface, const Color(0xfffafafa));
    expect(light.brightness, Brightness.light);
    expect(light.extension<Corners>()!.radius, 0);
  });
}
