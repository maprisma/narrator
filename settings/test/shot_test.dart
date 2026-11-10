import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/look.dart';
import 'package:maprisma_narrator/shot.dart';

Widget app() => MaterialApp(
  navigatorKey: shotNavigator,
  scaffoldMessengerKey: shotMessenger,
  builder: (context, child) => ShotScope(child: child!),
  home: const Scaffold(body: Text('hello')),
);

void main() {
  late Directory tmp;
  setUp(() {
    tmp = Directory.systemTemp.createTempSync('shot-widget-');
    debugScreenshotFolder = '${tmp.path}/Maprisma Narrator';
    lookSettingsFile = () => File('${tmp.path}/settings.json');
    look.value = const LookSettings();
  });
  tearDown(() {
    debugScreenshotFolder = null;
    tmp.deleteSync(recursive: true);
  });

  List<String> files() => Directory(debugScreenshotFolder!).existsSync()
      ? (Directory(debugScreenshotFolder!).listSync().map((f) => f.uri.pathSegments.last).toList()..sort())
      : [];

  testWidgets('F12 saves the window and a note typed into the dialog', (tester) async {
    await tester.pumpWidget(app());
    await tester.sendKeyEvent(LogicalKeyboardKey.f12);
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 300)));
    await tester.pumpAndSettle();
    expect(find.text('Screenshot saved'), findsOneWidget);
    final pictures = files();
    expect(pictures, hasLength(1));
    expect(pictures.single, matches(RegExp(r'^maprisma-narrator-\d{8}-\d{6}\.png$')));
    expect(File('${debugScreenshotFolder!}/${pictures.single}').readAsBytesSync().take(4), [0x89, 0x50, 0x4e, 0x47]);
    await tester.sendKeyEvent(LogicalKeyboardKey.f12); // no second picture while the note is asked for
    await tester.enterText(find.byType(TextField), 'The button is cut off');
    await tester.tap(find.text('Done'));
    await tester.pumpAndSettle();
    expect(files(), [pictures.single, pictures.single.replaceFirst('.png', '.txt')]);
    expect(File('${debugScreenshotFolder!}/${files().last}').readAsStringSync(), 'The button is cut off\n');
  });

  testWidgets('Esc skips the note; with Ctrl or switched off F12 does nothing', (tester) async {
    await tester.pumpWidget(app());
    await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
    await tester.sendKeyEvent(LogicalKeyboardKey.f12);
    await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
    look.value = const LookSettings(screenshotKey: false);
    await tester.sendKeyEvent(LogicalKeyboardKey.f12);
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 200)));
    await tester.pumpAndSettle();
    expect(files(), isEmpty);
    look.value = const LookSettings();
    await tester.sendKeyEvent(LogicalKeyboardKey.f12);
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 300)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'typed');
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(find.text('Screenshot saved'), findsNothing);
    expect(files(), hasLength(1));
    expect(files().single, endsWith('.png'));
  });
}
