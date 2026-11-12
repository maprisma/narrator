import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/app_theme.dart';
import 'package:maprisma_narrator/desktop_theme.dart';

void main() {
  test('portal accent is parsed, unset accent is ignored', () {
    expect(DesktopTheme.parseAccent([1.0, 0.678431, 0]), isNotNull);
    expect(DesktopTheme.parseAccent([-1.0, -1.0, -1.0]), isNull);
    expect(DesktopTheme.parseAccent(null), isNull);
  });

  test('dark theme has a dark snack bar', () {
    final theme = appTheme(Brightness.dark, const {}, 12);
    final bar = theme.snackBarTheme.backgroundColor!;
    expect(bar.computeLuminance(), lessThan(0.2));
    expect(theme.colorScheme.brightness, Brightness.dark);
  });
}
