import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/bridge.dart';
import 'package:maprisma_narrator/main.dart';
import 'package:maprisma_narrator/widgets.dart';
import 'package:maprisma_narrator/window.dart';

class _Bridge extends Bridge {
  _Bridge() : super(script: '/nonexistent');
  @override
  Future<Json> request(Json payload) async => {};
}

/// A page with a drop-down (ChoiceButton), a dialog (as the screenshot note) and a text field.
Widget _app(VoidCallback onClose) => MaterialApp(
  home: EscapeCloses(
    onClose: onClose,
    child: Scaffold(
      body: Column(
        children: [
          ChoiceButton(options: const [('a', 'Option A'), ('b', 'Option B')], value: 'a', onPick: (_) {}),
          Builder(
            builder: (context) => TextButton(
              onPressed: () => showDialog<void>(context: context, builder: (_) => const AlertDialog(title: Text('Note'))),
              child: const Text('Dialog'),
            ),
          ),
          const TextField(),
          const SizedBox(height: 200, width: 200, key: Key('empty')),
        ],
      ),
    ),
  ),
);

void main() {
  group('Esc', () {
    testWidgets('closes the window when nothing is open', (tester) async {
      var closed = 0;
      await tester.pumpWidget(_app(() => closed++));
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      expect(closed, 1);
    });

    testWidgets('closes an open drop-down first, then the window', (tester) async {
      var closed = 0;
      await tester.pumpWidget(_app(() => closed++));
      await tester.tap(find.text('Option A'));
      await tester.pumpAndSettle();
      expect(find.text('Option B'), findsOneWidget);
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pumpAndSettle();
      expect(find.text('Option B'), findsNothing);
      expect(closed, 0);
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      expect(closed, 1);
    });

    testWidgets('closes an open dialog first, then the window', (tester) async {
      var closed = 0;
      await tester.pumpWidget(_app(() => closed++));
      await tester.tap(find.text('Dialog'));
      await tester.pumpAndSettle();
      expect(find.text('Note'), findsOneWidget);
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pumpAndSettle();
      expect(find.text('Note'), findsNothing);
      expect(closed, 0);
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      expect(closed, 1);
    });

    testWidgets('closes the window from a text field and after it lets go of the focus', (tester) async {
      var closed = 0;
      await tester.pumpWidget(_app(() => closed++));
      await tester.tap(find.byType(TextField));
      await tester.pump();
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      expect(closed, 1);
      await tester.tap(find.byKey(const Key('empty')));
      await tester.pump();
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      expect(closed, 2);
    });

    testWidgets('closes the real window', (tester) async {
      var closed = 0;
      await tester.pumpWidget(SettingsApp(bridge: _Bridge(), onClose: () => closed++));
      await tester.pump();
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      expect(closed, 1);
      await tester.pumpWidget(const SizedBox());
    });
  });

  group('window size', () {
    const minimum = Size(420, 360);
    const fallback = Size(640, 820);

    test('parses only positive finite width and height', () {
      expect(AppWindow.parseSize({'width': 800, 'height': 600.5}), const Size(800, 600.5));
      for (final bad in [null, 'x', [], {'width': 800}, {'width': '800', 'height': 600}, {'width': 0, 'height': 10},
          {'width': -5, 'height': 10}, {'width': double.nan, 'height': 10}, {'width': double.infinity, 'height': 10}]) {
        expect(AppWindow.parseSize(bad), isNull, reason: '$bad');
      }
    });

    test('fits the saved size between the minimum and the screen', () {
      expect(AppWindow.fit(null, fallback: fallback, minimum: minimum), fallback);
      expect(AppWindow.fit(const Size(900, 700), fallback: fallback, minimum: minimum), const Size(900, 700));
      expect(AppWindow.fit(const Size(100, 50), fallback: fallback, minimum: minimum), minimum);
      expect(AppWindow.fit(const Size(4000, 3000), fallback: fallback, minimum: minimum, screen: const Size(1920, 1050)),
          const Size(1920, 1050));
      // A screen smaller than the minimum wins.
      expect(AppWindow.fit(null, fallback: fallback, minimum: minimum, screen: const Size(400, 300)), const Size(400, 300));
      expect(AppWindow.fit(const Size(700.4, 500.6), fallback: fallback, minimum: minimum), const Size(700, 501));
    });

    test('saves after the last resize, not while maximised, and restores', () async {
      final folder = Directory.systemTemp.createTempSync('window-size');
      addTearDown(() => folder.deleteSync(recursive: true));
      final file = File('${folder.path}/sub/window.json');
      final window = AppWindow(
        channel: const MethodChannel('test/window'),
        file: () => file,
        defaultSize: fallback,
        delay: const Duration(milliseconds: 20),
      );
      expect(window.readSaved(), isNull);
      window.resized({'width': 700, 'height': 500});
      window.resized({'width': 710, 'height': 510});
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(jsonDecode(file.readAsStringSync()), {'width': 710, 'height': 510});
      window.resized({'width': 1920, 'height': 1080, 'maximized': true});
      window.resized({'width': 1000, 'height': 900, 'tiled': true});
      window.resized({'width': 1920, 'height': 1080, 'fullscreen': true});
      window.resized({'width': 'x'});
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(window.readSaved(), const Size(710, 510));
      // A resize that is undone before the delay: nothing new to save.
      window.resized({'width': 800, 'height': 800, 'maximized': false});
      window.resized({'width': 710, 'height': 510});
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(window.readSaved(), const Size(710, 510));
      file.writeAsStringSync('{broken');
      expect(window.readSaved(), isNull);
      window.dispose();
    });

    testWidgets('restore sizes the window from the saved file, fitted to the screen', (tester) async {
      final folder = Directory.systemTemp.createTempSync('window-size');
      addTearDown(() => folder.deleteSync(recursive: true));
      final file = File('${folder.path}/window.json')..writeAsStringSync('{"width": 3000, "height": 200}');
      const channel = MethodChannel('test/window-restore');
      final calls = <MethodCall>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call);
        return call.method == 'screen' ? {'width': 1920, 'height': 1050} : null;
      });
      addTearDown(() => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, null));
      final window = AppWindow(channel: channel, file: () => file, defaultSize: fallback);
      await window.restore();
      expect(calls.last.method, 'resize');
      expect(calls.last.arguments, {'width': 1920, 'height': 360});
      await window.close();
      expect(calls.last.method, 'close');
    });

    testWidgets('restore without the runner keeps going', (tester) async {
      final window = AppWindow(
        channel: const MethodChannel('test/no-runner'),
        file: () => File('/nonexistent/window.json'),
        defaultSize: fallback,
      );
      await tester.runAsync(() async {
        await window.restore();
        await window.close();
      });
    });
  });
}
