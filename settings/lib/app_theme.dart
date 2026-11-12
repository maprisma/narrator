// The window's theme from the desktop's palette (desktop_look.dart), as Maprisma Manager builds
// it (maprisma-manager flutter_app theme.dart; Maprisma's app_theme.dart): the desktop's own
// background and accent, card tones stepped from the background, and Settings › Corners in
// three sizes.

import 'dart:math';

import 'package:flutter/material.dart';

Color? hexColor(Map colors, String key) {
  final value = colors[key];
  if (value is! String || !RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(value)) return null;
  return Color(0xff000000 | int.parse(value.substring(1), radix: 16));
}

String colorHex(Color c) => '#${(c.toARGB32() & 0xFFFFFF).toRadixString(16).padLeft(6, '0')}';

/// The corner radius in effect, in Maprisma's sizes: cards, dialogs, pop-ups and menus take
/// [radius]; buttons, choice boxes, fields, tooltips and chips [control] (at most 8); check boxes,
/// slider tracks and progress bars [small] (at most 4); toggles and pill badges [pill] (round, or
/// square with Square). The slider knob stays small (see [KnobShape]).
class Corners extends ThemeExtension<Corners> {
  const Corners(this.radius);
  final double radius;
  double get control => min(radius, 8);
  double get small => min(radius, 4);
  double get pill => radius > 0 ? 999 : 0;
  @override
  Corners copyWith({double? radius}) => Corners(radius ?? this.radius);
  @override
  Corners lerp(Corners? other, double t) => other ?? this;
}

/// Settings › Corners in its sizes (see [Corners]).
Corners cornerSizes(BuildContext context) => Theme.of(context).extension<Corners>() ?? const Corners(12);

/// "desktop" follows the desktop's window corners (12 when unknown), "slight" 6, "rounded" 12,
/// "square" 0. An unknown value counts as "desktop".
double cornerRadius(String setting, int? desktopRounding) => switch (setting) {
  'slight' => 6,
  'rounded' => 12,
  'square' => 0,
  _ => (desktopRounding ?? 12).toDouble(),
};

/// The state colours (ok, warning, error, update) from the desktop's palette: green, yellow,
/// red, orange; fixed ones only where the palette has none.
class StateColors extends ThemeExtension<StateColors> {
  const StateColors({required this.ok, required this.warn, required this.error, required this.update});
  final Color ok, warn, error, update;
  @override
  StateColors copyWith({Color? ok, Color? warn, Color? error, Color? update}) =>
      StateColors(ok: ok ?? this.ok, warn: warn ?? this.warn, error: error ?? this.error, update: update ?? this.update);
  @override
  StateColors lerp(StateColors? other, double t) => other ?? this;
}

StateColors stateColors(BuildContext context) =>
    Theme.of(context).extension<StateColors>() ??
    StateColors(
      ok: const Color(0xff26a269),
      warn: const Color(0xffc88800),
      error: Theme.of(context).colorScheme.error,
      update: const Color(0xffe66100),
    );

/// Light or dark from the desktop's background; the platform's without one.
ThemeMode appThemeMode(Map colors) {
  final background = hexColor(colors, 'background');
  if (background == null) return ThemeMode.system;
  return background.computeLuminance() < .5 ? ThemeMode.dark : ThemeMode.light;
}

/// The desktop's palette as a Material theme; an empty palette (other desktops) follows the
/// platform's light or dark with Material tones of the accent.
ThemeData appTheme(Brightness platform, Map colors, double radius) {
  final background = hexColor(colors, 'background');
  final accent = hexColor(colors, 'accent');
  final brightness =
      background == null ? platform : (background.computeLuminance() < .5 ? Brightness.dark : Brightness.light);
  var scheme = ColorScheme.fromSeed(
    seedColor: accent ?? const Color(0xff3584e4),
    brightness: brightness,
    // Keeps primary close to the desktop accent instead of a muted tone of it.
    dynamicSchemeVariant: accent == null ? DynamicSchemeVariant.tonalSpot : DynamicSchemeVariant.fidelity,
  );
  if (background != null) {
    final foreground = hexColor(colors, 'foreground') ?? scheme.onSurface;
    final muted = hexColor(colors, 'muted');
    Color step(double amount) => Color.lerp(background, foreground, amount)!;
    scheme = scheme.copyWith(
      // The desktop's own accent, not a Material tone of it.
      primary: accent ?? scheme.primary,
      onPrimary: accent == null ? null : (accent.computeLuminance() > .4 ? Colors.black : Colors.white),
      surface: background,
      onSurface: foreground,
      onSurfaceVariant: muted == null ? step(.6) : Color.lerp(muted, foreground, .35),
      surfaceContainerLowest: step(.02),
      surfaceContainerLow: step(.05),
      surfaceContainer: step(.08),
      surfaceContainerHigh: step(.11),
      surfaceContainerHighest: step(.14),
      outlineVariant: step(.18),
      secondaryContainer: hexColor(colors, 'selection') ?? step(.2),
      error: hexColor(colors, 'red') ?? scheme.error,
    );
  }
  final sizes = Corners(radius);
  RoundedRectangleBorder round(double r) => RoundedRectangleBorder(borderRadius: BorderRadius.circular(r));
  final shape = round(radius), controlShape = round(sizes.control);
  final menu = MenuStyle(
    backgroundColor: WidgetStatePropertyAll(scheme.surfaceContainerHigh),
    shape: WidgetStatePropertyAll(shape),
  );
  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    scaffoldBackgroundColor: scheme.surface,
    visualDensity: VisualDensity.compact,
    materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    extensions: [
      sizes,
      StateColors(
        ok: hexColor(colors, 'green') ?? const Color(0xff26a269),
        warn: hexColor(colors, 'yellow') ?? const Color(0xffc88800),
        error: scheme.error,
        update: hexColor(colors, 'orange') ?? const Color(0xffe66100),
      ),
    ],
    // Every card as Maprisma's SectionCard: one step up from the page, a thin edge.
    cardTheme: CardThemeData(
      color: scheme.surfaceContainerLow,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(radius),
        side: BorderSide(color: scheme.outlineVariant),
      ),
    ),
    dialogTheme: DialogThemeData(shape: shape, backgroundColor: scheme.surfaceContainerHigh),
    popupMenuTheme: PopupMenuThemeData(color: scheme.surfaceContainerHigh, shape: shape),
    menuTheme: MenuThemeData(style: menu),
    dropdownMenuTheme: DropdownMenuThemeData(menuStyle: menu),
    // Material's default snack bar is the inverse surface: a white bar in a dark window.
    snackBarTheme: SnackBarThemeData(
      backgroundColor: scheme.surfaceContainerHighest,
      contentTextStyle: TextStyle(color: scheme.onSurface),
      actionTextColor: scheme.primary,
      closeIconColor: scheme.onSurfaceVariant,
      elevation: 0,
      shape: Border(top: BorderSide(color: scheme.outlineVariant)),
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(color: scheme.inverseSurface, borderRadius: BorderRadius.circular(sizes.control)),
    ),
    filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(shape: controlShape)),
    outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(shape: controlShape)),
    textButtonTheme: TextButtonThemeData(style: TextButton.styleFrom(shape: controlShape)),
    elevatedButtonTheme: ElevatedButtonThemeData(style: ElevatedButton.styleFrom(shape: controlShape)),
    iconButtonTheme: IconButtonThemeData(style: IconButton.styleFrom(shape: controlShape)),
    segmentedButtonTheme: SegmentedButtonThemeData(style: SegmentedButton.styleFrom(shape: controlShape)),
    chipTheme: ChipThemeData(shape: round(sizes.pill)),
    checkboxTheme: CheckboxThemeData(shape: round(sizes.small)),
    progressIndicatorTheme: ProgressIndicatorThemeData(borderRadius: BorderRadius.circular(sizes.small)),
    // Square squares the slider too, but keeps its knob small (no block).
    sliderTheme: SliderThemeData(
      trackShape: radius <= 0 ? const RectangularSliderTrackShape() : const RoundedRectSliderTrackShape(),
      thumbShape: KnobShape(square: radius <= 0),
    ),
  );
}

/// The slider's knob: 14 px, round, or square with Square corners (not a big block).
class KnobShape extends SliderComponentShape {
  const KnobShape({this.square = false});
  final bool square;
  static const _side = 14.0;

  @override
  Size getPreferredSize(bool isEnabled, bool isDiscrete) => const Size.square(_side);

  @override
  void paint(
    PaintingContext context,
    Offset center, {
    required Animation<double> activationAnimation,
    required Animation<double> enableAnimation,
    required bool isDiscrete,
    required TextPainter labelPainter,
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required TextDirection textDirection,
    required double value,
    required double textScaleFactor,
    required Size sizeWithOverflow,
  }) {
    final paint = Paint()..color = sliderTheme.thumbColor ?? Colors.grey;
    final box = Rect.fromCenter(center: center, width: _side, height: _side);
    square ? context.canvas.drawRect(box, paint) : context.canvas.drawOval(box, paint);
  }
}
