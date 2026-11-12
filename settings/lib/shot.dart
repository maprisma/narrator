// F12 in the window: the whole window (dialogs included) as a PNG, then a dialog for a note.
// MaterialApp gets [shotNavigator] and [shotMessenger]; its builder wraps the page in [ShotScope].

import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import 'app_look.dart';
import 'app_theme.dart';
import 'i18n.dart';
import 'look.dart';
import 'screenshot.dart';

final shotNavigator = GlobalKey<NavigatorState>(debugLabel: 'navigator');
final shotMessenger = GlobalKey<ScaffoldMessengerState>(debugLabel: 'messenger');

/// Where F12 saves its pictures (tests); null: `~/Pictures/<App>`.
String? debugScreenshotFolder;

class ShotScope extends StatefulWidget {
  const ShotScope({super.key, required this.child});
  final Widget child;
  @override
  State<ShotScope> createState() => ShotScopeState();
}

class ShotScopeState extends State<ShotScope> {
  final _boundary = GlobalKey(debugLabel: 'window');
  bool _shooting = false;

  @override
  void initState() {
    super.initState();
    HardwareKeyboard.instance.addHandler(_f12);
  }

  @override
  void dispose() {
    HardwareKeyboard.instance.removeHandler(_f12);
    super.dispose();
  }

  /// F12 without Ctrl, Shift, Alt or Super, wherever the keyboard is (also in a dialog).
  bool _f12(KeyEvent event) {
    if (event is! KeyDownEvent || event.logicalKey != LogicalKeyboardKey.f12) return false;
    final keys = HardwareKeyboard.instance;
    if (keys.isControlPressed || keys.isShiftPressed || keys.isAltPressed || keys.isMetaPressed) return false;
    if (!look.value.screenshotKey) return false;
    takeScreenshot();
    return true;
  }

  static String _why(Object error) => switch (error) {
    FileSystemException(:final osError?) => osError.message,
    FileSystemException(:final message) => message,
    _ => '$error',
  };

  void _toast(String text) => shotMessenger.currentState
    ?..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(text), duration: const Duration(seconds: 6)));

  /// The window as it is now into a PNG (it draws itself: no screenshot program), then the
  /// dialog for a note. F12 again meanwhile takes no second picture.
  Future<void> takeScreenshot() async {
    if (_shooting) return;
    _shooting = true;
    String path;
    try {
      final boundary = _boundary.currentContext?.findRenderObject();
      if (boundary is! RenderRepaintBoundary || !boundary.hasSize || boundary.size.isEmpty) {
        throw const FileSystemException('the window could not be drawn');
      }
      final image = await boundary.toImage(pixelRatio: View.of(context).devicePixelRatio);
      final ByteData? png;
      try {
        png = await image.toByteData(format: ui.ImageByteFormat.png);
      } finally {
        image.dispose();
      }
      if (png == null) throw const FileSystemException('the window could not be drawn');
      path = saveScreenshot(debugScreenshotFolder ?? screenshotFolder(screenshotApp), screenshotSlug,
          png.buffer.asUint8List(png.offsetInBytes, png.lengthInBytes));
    } on Object catch (e) {
      _shooting = false;
      _toast(trf('The screenshot could not be saved: {0}', [_why(e)]));
      return;
    }
    try {
      final navigator = shotNavigator.currentContext;
      if (!mounted || navigator == null || !navigator.mounted) return;
      final note = await showDialog<String>(context: navigator, builder: (_) => ScreenshotNoteDialog(path: path));
      try {
        saveScreenshotNote(path, note ?? '');
      } on Object catch (e) {
        _toast(trf('The note could not be saved: {0}', [_why(e)]));
      }
    } finally {
      _shooting = false;
    }
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(key: _boundary, child: widget.child);
}

/// "Screenshot saved": where, and a field for what is wrong. Done and Enter give the note,
/// Esc gives none.
class ScreenshotNoteDialog extends StatefulWidget {
  const ScreenshotNoteDialog({super.key, required this.path});
  final String path;
  @override
  State<ScreenshotNoteDialog> createState() => _ScreenshotNoteDialogState();
}

class _ScreenshotNoteDialogState extends State<ScreenshotNoteDialog> {
  final _note = TextEditingController();

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  void _done() => Navigator.of(context).pop(_note.text);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return AlertDialog(
      title: Text(tr('Screenshot saved')),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(trf('Saved as {0}', [homeShort(widget.path)]),
                style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
            const SizedBox(height: AppSpace.md),
            TextField(
              controller: _note,
              autofocus: true,
              maxLength: screenshotNoteLimit,
              textInputAction: TextInputAction.done,
              onSubmitted: (_) => _done(),
              decoration: InputDecoration(
                hintText: tr('What is wrong? (optional)'),
                isDense: true,
                counterText: '',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(cornerSizes(context).control)),
              ),
            ),
          ],
        ),
      ),
      actions: [FilledButton(onPressed: _done, child: Text(tr('Done')))],
    );
  }
}
