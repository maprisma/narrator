// The GTK runner's header CSS and Hyprland check (C++, so checked in its source here).

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  final runner = File('linux/runner/my_application.cc').readAsStringSync();

  test('header bar CSS: colours only, as Maprisma Settings (no clipped buttons on Breeze)', () {
    expect(runner, contains('headerbar, headerbar:backdrop, .titlebar, .titlebar:backdrop {'));
    expect(runner, contains('headerbar .title, headerbar button, headerbar button image {'));
    // These overrides cut KDE's (Breeze GTK) window buttons in half.
    expect(runner, isNot(contains('border-color: transparent')));
    expect(runner, isNot(contains('window, decoration {')));
    expect(runner, isNot(contains('headerbar button:hover')));
  });

  test('Hyprland only by XDG_CURRENT_DESKTOP, or a live socket without it', () {
    expect(runner, contains('static gboolean in_hyprland_session()'));
    expect(runner, contains('gboolean on_hyprland = in_hyprland_session();'));
    expect(runner, contains('".socket.sock"'));
    // The bare signature (stale after a Hyprland session) never decides alone.
    expect(RegExp(r'on_hyprland = hypr != nullptr').hasMatch(runner), isFalse);
  });
}
