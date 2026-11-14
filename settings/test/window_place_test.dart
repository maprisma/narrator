import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/window.dart';

void main() {
  const clients = '[{"pid": 7, "floating": true, "fullscreen": 0, "at": [2860, 42], "size": [560, 700]},'
      '{"pid": 8, "floating": false, "fullscreen": 0, "at": [0, 0], "size": [10, 10]}]';
  const monitors = '[{"x": 0, "y": 0, "width": 3840, "height": 2160, "scale": 2.0}]';
  const hypr = {'XDG_CURRENT_DESKTOP': 'Hyprland'};

  test('places from hyprctl and the file; a place must stay on a screen', () {
    expect(hyprPosition(clients, 7), (2860, 42));
    expect(hyprPosition(clients, 8), isNull); // tiled
    expect(hyprPosition(clients, 9), isNull);
    expect(AppWindow.parsePlace({'x': -20, 'y': 42}), (-20, 42));
    expect(AppWindow.parsePlace({'x': 1.5, 'y': 2}), isNull);
    expect(AppWindow.parsePlace({'x': 200000, 'y': 2}), isNull);
    expect(AppWindow.parsePlace('x'), isNull);
    expect(onAMonitor(monitors, (1300, 42), (560, 700)), isTrue);
    expect(onAMonitor(monitors, (2000, 42), (560, 700)), isFalse); // past the 1920 px logical width
    expect(onAMonitor('nonsense', (0, 0), (560, 700)), isFalse);
  });

  test('the place is kept next to the size in window.json, and the size next to the place', () {
    final folder = Directory.systemTemp.createTempSync('window-place');
    addTearDown(() => folder.deleteSync(recursive: true));
    final file = File('${folder.path}/sub/window.json');
    final window = AppWindow(channel: const MethodChannel('test/window-place'), file: () => file, defaultSize: const Size(640, 820));
    expect(window.readPlace(), isNull);
    window.savePlace(300, -60);
    expect(jsonDecode(file.readAsStringSync()), {'x': 300, 'y': -60});
    window.save(const Size(700, 500));
    expect(jsonDecode(file.readAsStringSync()), {'width': 700, 'height': 500, 'x': 300, 'y': -60});
    window.savePlace(10, 20);
    expect(window.readPlace(), (10, 20));
    expect(window.readSaved(), const Size(700, 500));
  });

  test('a moved window is saved once; shown again it is moved back; only on Hyprland, never in tests', () async {
    final calls = <List<String>>[];
    var now = '[{"pid": 7, "floating": true, "fullscreen": 0, "at": [100, 50], "size": [560, 700]}]';
    Future<ProcessResult> run(List<String> args) async {
      calls.add(args);
      final out = args.contains('clients') ? now : args.contains('monitors') ? monitors : '';
      return ProcessResult(0, 0, out, '');
    }

    final saved = <(int, int)>[];
    final keeper = WindowPlaceKeeper(saved: (300, 60), save: (x, y) => saved.add((x, y)), environment: hypr, run: run, processId: 7);
    await keeper.restore();
    expect(calls.last, ['eval', "hl.dispatch(hl.dsp.window.move({ x = 300, y = 60, window = 'pid:7' }))"]);
    await keeper.sample(); // still at 100,50 in the fake: that is where it is now
    expect(saved, [(100, 50)]);
    await keeper.sample();
    expect(saved, [(100, 50)]); // unchanged: not saved again
    now = '[{"pid": 7, "floating": false, "fullscreen": 0, "at": [0, 0], "size": [560, 700]}]';
    await keeper.sample();
    expect(saved, [(100, 50)]); // tiled: not the user's place

    expect(WindowPlaceKeeper(saved: null, save: (x, y) {}, environment: const {'XDG_CURRENT_DESKTOP': 'KDE'}).active, isFalse);
    expect(WindowPlaceKeeper(saved: null, save: (x, y) {}, environment: const {...hypr, 'FLUTTER_TEST': 'true'}).active, isFalse);
    // inactive: lifecycle changes ask nothing
    final before = calls.length;
    WindowPlaceKeeper(saved: (1, 1), save: (x, y) {}, environment: const {'XDG_CURRENT_DESKTOP': 'KDE'}, run: run)
      ..lifecycle(AppLifecycleState.hidden)
      ..lifecycle(AppLifecycleState.resumed);
    await Future<void>.delayed(const Duration(milliseconds: 120));
    expect(calls.length, before);
  });
}
