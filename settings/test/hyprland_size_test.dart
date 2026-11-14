import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/window.dart';

void main() {
  const clients =
      '[{"pid": 10, "floating": true, "fullscreen": 0}, {"pid": 11, "floating": false, "fullscreen": 0},'
      ' {"pid": 12, "floating": true, "fullscreen": 2}]';

  test('Hyprland: only a floating, not fullscreen window has the user\'s size', () {
    expect(hyprNotUsers(clients, 10), isFalse);
    expect(hyprNotUsers(clients, 11), isTrue);
    expect(hyprNotUsers(clients, 12), isTrue);
    expect(hyprNotUsers(clients, 99), isNull);
    expect(hyprNotUsers('not json', 10), isNull);
  });

  test('hyprctl is asked only in a Hyprland session', () async {
    var asked = 0;
    Future<ProcessResult> run() async {
      asked++;
      return ProcessResult(0, 0, clients, '');
    }

    expect(
      await hyprlandSizeNotUsers(environment: {'XDG_CURRENT_DESKTOP': 'KDE'}, processId: 11, clients: run),
      isFalse,
    );
    expect(
      await hyprlandSizeNotUsers(
        environment: {'XDG_CURRENT_DESKTOP': 'COSMIC', 'HYPRLAND_INSTANCE_SIGNATURE': 'x'},
        processId: 11,
        clients: run,
      ),
      isFalse,
    );
    expect(asked, 0);
    expect(
      await hyprlandSizeNotUsers(environment: {'XDG_CURRENT_DESKTOP': 'Hyprland'}, processId: 11, clients: run),
      isTrue,
    );
    expect(
      await hyprlandSizeNotUsers(
        environment: {'MAPRISMA_DESKTOP': 'hyprland', 'XDG_CURRENT_DESKTOP': 'KDE'},
        processId: 10,
        clients: run,
      ),
      isFalse,
    );
    expect(asked, 2);
  });
}
