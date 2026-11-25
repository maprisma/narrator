import 'package:flutter/material.dart';

import 'app_theme.dart';

const String skinKey = 'skin';
const List<String> appSkins = [
  'native',
  'synthwave',
  'cozy',
  'terminal',
  'disco',
  'zen',
];

class AppSkinStyle {
  const AppSkinStyle({
    required this.accent,
    required this.borderTint,
    required this.bgTint,
    required this.windowBg,
    required this.foreground,
    required this.borderWidth,
  });

  final Color accent, borderTint, bgTint, windowBg, foreground;
  final double borderWidth;

  Map<String, String> toDesktopColors() => {
    'accent': colorHex(accent),
    'background': colorHex(windowBg),
    'foreground': colorHex(foreground),
  };
}

String normalizeSkin(String? raw) => appSkins.contains(raw) ? raw! : 'native';

AppSkinStyle? skinStyle(String? skin) => switch (normalizeSkin(skin)) {
  'synthwave' => const AppSkinStyle(
    accent: Color(0xffff2e93),
    borderTint: Color(0xff00e5ff),
    bgTint: Color(0xff3a1259),
    windowBg: Color(0xff130924),
    foreground: Color(0xfff4eaff),
    borderWidth: 1.5,
  ),
  'cozy' => const AppSkinStyle(
    accent: Color(0xfff09a36),
    borderTint: Color(0xffe0822a),
    bgTint: Color(0xff593012),
    windowBg: Color(0xff21150e),
    foreground: Color(0xfff5e8d6),
    borderWidth: 1.25,
  ),
  'terminal' => const AppSkinStyle(
    accent: Color(0xff2ce868),
    borderTint: Color(0xff22c55e),
    bgTint: Color(0xff0d381a),
    windowBg: Color(0xff09130b),
    foreground: Color(0xffd2fce0),
    borderWidth: 1.25,
  ),
  'disco' => const AppSkinStyle(
    accent: Color(0xffd946ef),
    borderTint: Color(0xfffacc15),
    bgTint: Color(0xff4c1666),
    windowBg: Color(0xff1c0c2b),
    foreground: Color(0xfff8ecff),
    borderWidth: 1.5,
  ),
  'zen' => const AppSkinStyle(
    accent: Color(0xff52b798),
    borderTint: Color(0xff64c2a4),
    bgTint: Color(0xff1e3832),
    windowBg: Color(0xff141d1c),
    foreground: Color(0xffe2f0ec),
    borderWidth: 1.0,
  ),
  _ => null,
};

String skinLabel(String? skin, String Function(String) tr) =>
    tr(switch (normalizeSkin(skin)) {
      'synthwave' => 'Synthwave',
      'cozy' => 'Cozy',
      'terminal' => 'Terminal',
      'disco' => 'Disco',
      'zen' => 'Zen',
      _ => 'Native',
    });

/// Skin surfaces start opaque; window_style.dart applies window transparency afterwards.
ThemeData applySkinToTheme(ThemeData base, String? skin, {double? radius}) {
  final st = skinStyle(skin);
  if (st == null) return base;
  final r = radius ?? base.extension<Corners>()?.radius ?? 12;
  final sizes = Corners(r);
  Color blend(Color color, double alpha) =>
      Color.alphaBlend(color.withValues(alpha: alpha), st.windowBg);
  final scheme = base.colorScheme.copyWith(
    brightness: Brightness.dark,
    primary: st.accent,
    onPrimary: st.accent.computeLuminance() > .4 ? Colors.black : Colors.white,
    secondary: st.accent,
    surface: st.windowBg,
    onSurface: st.foreground,
    onSurfaceVariant: Color.lerp(st.windowBg, st.foreground, .65),
    surfaceContainerLowest: blend(st.bgTint, .12),
    surfaceContainerLow: blend(st.bgTint, .20),
    surfaceContainer: blend(st.bgTint, .28),
    surfaceContainerHigh: blend(st.bgTint, .38),
    surfaceContainerHighest: blend(st.bgTint, .48),
    outlineVariant: st.borderTint.withValues(alpha: .42),
    secondaryContainer: blend(st.accent, .22),
  );
  final card = blend(st.bgTint, .28);
  final menu = MenuStyle(
    backgroundColor: WidgetStatePropertyAll(scheme.surfaceContainerHigh),
    shape: WidgetStatePropertyAll(
      RoundedRectangleBorder(borderRadius: BorderRadius.circular(r)),
    ),
  );
  return base.copyWith(
    colorScheme: scheme,
    scaffoldBackgroundColor: st.windowBg,
    canvasColor: st.windowBg,
    cardTheme: base.cardTheme.copyWith(
      color: card,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(r),
        side: BorderSide(
          color: st.borderTint.withValues(alpha: .48),
          width: st.borderWidth,
        ),
      ),
    ),
    dialogTheme: base.dialogTheme.copyWith(
      backgroundColor: scheme.surfaceContainerHigh,
    ),
    popupMenuTheme: base.popupMenuTheme.copyWith(
      color: scheme.surfaceContainerHigh,
    ),
    menuTheme: MenuThemeData(style: menu),
    dropdownMenuTheme: DropdownMenuThemeData(menuStyle: menu),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: blend(st.accent, .24),
      side: BorderSide(color: st.borderTint.withValues(alpha: .48)),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(sizes.pill),
      ),
    ),
    dividerTheme: base.dividerTheme.copyWith(color: scheme.outlineVariant),
    snackBarTheme: base.snackBarTheme.copyWith(
      backgroundColor: scheme.surfaceContainerHighest,
      contentTextStyle: TextStyle(color: st.foreground),
      actionTextColor: st.accent,
    ),
  );
}
