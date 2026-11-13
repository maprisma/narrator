// The desktop's palette and window corners, read as Maprisma Manager reads them
// (maprisma_manager_core desktop_look.dart): Maprisma Shell's scheme.json on Hyprland (written by
// Maprisma Theme), the COSMIC theme on COSMIC, kdeglobals on KDE; nothing elsewhere (the
// toolkit's colours). Pure Dart: no Flutter, so it is tested without a window.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// `{accent, background, foreground, muted, selection, red, yellow, orange, green}` as `#rrggbb`
/// (only those the desktop knows), the windows' corner [rounding] (null: unknown) and whether the
/// background is dark (null: no background).
class DesktopLook {
  const DesktopLook({this.desktop = 'other', this.colors = const {}, this.rounding});

  final String desktop;
  final Map<String, String> colors;
  final int? rounding;

  bool? get isDark {
    final bg = colors['background'];
    return bg == null ? null : darkHex(bg);
  }

  @override
  bool operator ==(Object other) =>
      other is DesktopLook &&
      other.desktop == desktop &&
      other.rounding == rounding &&
      other.colors.length == colors.length &&
      colors.entries.every((e) => other.colors[e.key] == e.value);

  @override
  int get hashCode => Object.hash(desktop, rounding, Object.hashAllUnordered(colors.entries.map((e) => '${e.key}=${e.value}')));

  @override
  String toString() => 'DesktopLook($desktop, $colors, rounding: $rounding)';
}

/// COSMIC / KDE / Hyprland / other from XDG_CURRENT_DESKTOP. Without it (a process started
/// outside the session's environment) the session's other marks decide: XDG_SESSION_DESKTOP /
/// DESKTOP_SESSION (names or session-file paths), then HYPRLAND_INSTANCE_SIGNATURE and
/// KDE_FULL_SESSION (as the Rust apps' look.rs).
String desktopName(Map<String, String> env) {
  final current = (env['XDG_CURRENT_DESKTOP'] ?? '').trim();
  if (current.isEmpty) return _sessionDesktop(env);
  final names = current.toUpperCase().split(':');
  if (names.contains('COSMIC')) return 'cosmic';
  if (names.contains('KDE')) return 'kde';
  if (names.contains('HYPRLAND')) return 'hyprland';
  return 'other';
}

String _sessionDesktop(Map<String, String> env) {
  final session = '${env['XDG_SESSION_DESKTOP'] ?? ''}:${env['DESKTOP_SESSION'] ?? ''}';
  for (final part in session.split(':')) {
    final name = part.split('/').last.replaceFirst(RegExp(r'\.desktop$'), '').toLowerCase();
    if (name == 'cosmic' || name.startsWith('cosmic-')) return 'cosmic';
    if (name == 'kde' || name.startsWith('plasma')) return 'kde';
    if (name.startsWith('hyprland')) return 'hyprland';
  }
  if ((env['HYPRLAND_INSTANCE_SIGNATURE'] ?? '').isNotEmpty) return 'hyprland';
  if ((env['KDE_FULL_SESSION'] ?? '').toLowerCase() == 'true') return 'kde';
  return 'other';
}

/// The look of the desktop in [env] (default: this process' environment). [root] is the file
/// system's root (tests point it elsewhere); [hyprRounding] is Hyprland's decoration:rounding
/// (from `hyprctl`, see [DesktopLookWatcher]).
DesktopLook readDesktopLook({Map<String, String>? env, String root = '/', int? hyprRounding}) {
  final e = env ?? Platform.environment;
  final desktop = desktopName(e);
  final home = e['HOME'] ?? '';
  String xdg(String key, String fallback) {
    final v = e[key];
    return v != null && v.startsWith('/') ? v : '$home/$fallback';
  }

  final config = xdg('XDG_CONFIG_HOME', '.config');
  final state = xdg('XDG_STATE_HOME', '.local/state');
  return switch (desktop) {
    'cosmic' => DesktopLook(desktop: desktop, colors: _cosmicColors(config, root), rounding: _cosmicRounding(config, root)),
    'kde' => DesktopLook(desktop: desktop, colors: _kdeColors(config), rounding: 8),
    'hyprland' => DesktopLook(desktop: desktop, colors: shellColors(_read('$state/maprisma-shell/scheme.json', 256 * 1024)), rounding: hyprRounding),
    _ => const DesktopLook(),
  };
}

/// Re-reads the look while the app runs: the files at most every 5 s, `hyprctl` at most every
/// 30 s (Maprisma Theme can change the scheme at any time).
class DesktopLookWatcher {
  DesktopLookWatcher({Map<String, String>? env, this.root = '/', Future<int?> Function()? hyprRounding})
      : env = env ?? Platform.environment,
        _hyprctl = hyprRounding ?? hyprctlRounding;

  final Map<String, String> env;
  final String root;
  final Future<int?> Function() _hyprctl;
  static const filesEvery = Duration(seconds: 5), hyprctlEvery = Duration(seconds: 30);

  DesktopLook? _look;
  DateTime? _filesAt, _hyprAt;
  int? _rounding;

  Future<DesktopLook> read({DateTime? now}) async {
    final at = now ?? DateTime.now();
    if (desktopName(env) == 'hyprland' && (_hyprAt == null || at.difference(_hyprAt!) >= hyprctlEvery)) {
      _hyprAt = at;
      _rounding = await _hyprctl();
      _filesAt = null; // the new rounding goes in at once
    }
    if (_look == null || _filesAt == null || at.difference(_filesAt!) >= filesEvery) {
      _filesAt = at;
      _look = readDesktopLook(env: env, root: root, hyprRounding: _rounding);
    }
    return _look!;
  }
}

/// `hyprctl -j getoption decoration:rounding` → `.int` (0–64), or null.
Future<int?> hyprctlRounding() async {
  try {
    final result = await Process.run('hyprctl', ['-j', 'getoption', 'decoration:rounding'])
        .timeout(const Duration(seconds: 2));
    if (result.exitCode != 0) return null;
    return parseHyprRounding('${result.stdout}');
  } on Object {
    return null;
  }
}

int? parseHyprRounding(String json) {
  try {
    final data = jsonDecode(json);
    final v = data is Map ? data['int'] : null;
    return v is int && v >= 0 && v <= 64 ? v : null;
  } on FormatException {
    return null;
  }
}

/// Maprisma Shell's colour scheme (`{"colours": {<Material name>: "rrggbb"}}`); empty without it.
Map<String, String> shellColors(String? text) {
  if (text == null) return {};
  Object? data;
  try {
    data = jsonDecode(text);
  } on FormatException {
    return {};
  }
  final colours = data is Map ? data['colours'] : null;
  if (colours is! Map) return {};
  String? c(String key) {
    final v = colours[key];
    return v is String && RegExp(r'^[0-9a-fA-F]{6}$').hasMatch(v) ? '#${v.toLowerCase()}' : null;
  }

  final out = {
    'accent': c('primary'),
    'background': c('surface') ?? c('background'),
    'foreground': c('onSurface'),
    'muted': c('outline'),
    'selection': c('surfaceContainerHighest'),
    'red': c('error') ?? c('red'),
    'yellow': c('yellow'),
    'orange': c('peach'),
    'green': c('green'),
  };
  return {for (final e in out.entries) if (e.value != null) e.key: e.value!};
}

const lightFallback = {
  'background': '#fafafb', 'foreground': '#323233', 'muted': '#77767b',
  'selection': '#dedddf', 'red': '#e01b24', 'yellow': '#c88800',
  'orange': '#e66100', 'green': '#26a269',
};
const darkFallback = {
  'background': '#222226', 'foreground': '#ffffff', 'muted': '#9a9996',
  'selection': '#3a3a3e', 'red': '#ff7b63', 'yellow': '#f8e45c',
  'orange': '#ffa348', 'green': '#8ff0a4',
};

bool darkHex(String hex) {
  final v = int.parse(hex.substring(1), radix: 16);
  final r = (v >> 16) & 255, g = (v >> 8) & 255, b = v & 255;
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.5;
}

String? _read(String path, int max) {
  try {
    final f = File(path);
    if (FileSystemEntity.typeSync(path) != FileSystemEntityType.file || f.lengthSync() > max) return null;
    return utf8.decode(f.readAsBytesSync(), allowMalformed: true);
  } on FileSystemException {
    return null;
  }
}

// --- COSMIC ----------------------------------------------------------------------------------

String? _cosmicConfig(String config, String root, String component, String key) {
  for (final base in ['$config/cosmic', '${root.endsWith('/') ? root : '$root/'}usr/share/cosmic']) {
    final text = _read('$base/$component/v1/$key', 256 * 1024);
    if (text != null) return text;
  }
  return null;
}

String _cosmicTheme(String config, String root) =>
    (_cosmicConfig(config, root, 'com.system76.CosmicTheme.Mode', 'is_dark') ?? 'true').trim() != 'false'
        ? 'com.system76.CosmicTheme.Dark'
        : 'com.system76.CosmicTheme.Light';

Map<String, String> _cosmicColors(String config, String root) {
  final theme = _cosmicTheme(config, root);
  String? container(String key, String field) {
    final text = _cosmicConfig(config, root, theme, key);
    return text == null ? null : ronColor(ronField(text, field));
  }

  final accent = container('accent', 'base') ?? ronColor(_cosmicConfig(config, root, theme, 'accent'));
  return {
    ...(theme.endsWith('Dark') ? darkFallback : lightFallback),
    'accent': accent ?? '#63d0df',
    'background': ?container('background', 'base'),
    'foreground': ?container('background', 'on'),
    'green': ?container('success', 'base'),
    'yellow': ?container('warning', 'base'),
    'red': ?container('destructive', 'base'),
  };
}

int _cosmicRounding(String config, String root) {
  final radii = _cosmicConfig(config, root, _cosmicTheme(config, root), 'corner_radii');
  final small = radii == null ? null : ronField(radii, 'radius_s');
  final first = small == null ? null : RegExp(r'([0-9.]+)').firstMatch(small)?[1];
  return first == null ? 8 : double.tryParse(first)?.round() ?? 8;
}

/// The value after `key:` at the first nesting level of a RON struct, or null.
String? ronField(String text, String key) {
  var depth = 0;
  for (var i = 0; i < text.length; i++) {
    final c = text[i];
    if (c == '(' || c == '[') {
      depth++;
    } else if (c == ')' || c == ']') {
      depth--;
    } else if (depth == 1 && text.startsWith(key, i) && (i == 0 || !RegExp(r'\w').hasMatch(text[i - 1]))) {
      var j = i + key.length;
      while (j < text.length && text[j] == ' ') {
        j++;
      }
      if (j >= text.length || text[j] != ':') continue;
      j++;
      final start = j;
      var d = 0;
      for (; j < text.length; j++) {
        final cj = text[j];
        if (cj == '(' || cj == '[') d++;
        if (cj == ')' || cj == ']') {
          if (d == 0) break;
          d--;
        }
        if (cj == ',' && d == 0) break;
      }
      return text.substring(start, j).trim();
    }
  }
  return null;
}

/// A RON colour `(red: 0.1, green: …, blue: …)` as #rrggbb, or null.
String? ronColor(String? value) {
  if (value == null) return null;
  int? part(String name) {
    final m = RegExp('$name:\\s*([0-9.eE+-]+)').firstMatch(value);
    final v = m == null ? null : double.tryParse(m[1]!);
    return v == null ? null : (v.clamp(0, 1) * 255).round();
  }

  final r = part('red'), g = part('green'), b = part('blue');
  if (r == null || g == null || b == null) return null;
  String hex(int v) => v.toRadixString(16).padLeft(2, '0');
  return '#${hex(r)}${hex(g)}${hex(b)}';
}

// --- KDE -------------------------------------------------------------------------------------

String? _kdeIni(String text, String group, String key) {
  String? current, found;
  for (final raw in const LineSplitter().convert(text)) {
    final line = raw.trim();
    if (line.startsWith('[') && line.endsWith(']')) {
      current = line.substring(1, line.length - 1);
    } else if (current == group) {
      final eq = line.indexOf('=');
      if (eq > 0 && line.substring(0, eq).trim() == key) found = line.substring(eq + 1).trim();
    }
  }
  return found;
}

String? _kdeColor(String? value) {
  if (value == null) return null;
  final parts = value.split(',').map((v) => int.tryParse(v.trim())).toList();
  if ((parts.length != 3 && parts.length != 4) || parts.any((v) => v == null || v < 0 || v > 255)) return null;
  String hex(int v) => v.toRadixString(16).padLeft(2, '0');
  return '#${hex(parts[0]!)}${hex(parts[1]!)}${hex(parts[2]!)}';
}

/// Plasma's colour scheme from kdeglobals' text.
Map<String, String> kdeColors(String text) {
  String? c(String group, String key) => _kdeColor(_kdeIni(text, group, key));
  final bg = c('Colors:Window', 'BackgroundNormal');
  return {
    ...(bg == null || darkHex(bg) ? darkFallback : lightFallback),
    'accent': c('General', 'AccentColor') ?? c('Colors:View', 'DecorationFocus') ?? c('Colors:Selection', 'BackgroundNormal') ?? '#3daee9',
    'background': ?bg,
    'foreground': ?c('Colors:Window', 'ForegroundNormal'),
    'selection': ?c('Colors:Selection', 'BackgroundNormal'),
    'muted': ?c('Colors:Window', 'ForegroundInactive'),
    'red': ?c('Colors:View', 'ForegroundNegative'),
    'yellow': ?c('Colors:View', 'ForegroundNeutral'),
    'green': ?c('Colors:View', 'ForegroundPositive'),
  };
}

Map<String, String> _kdeColors(String config) => kdeColors(_read('$config/kdeglobals', 1024 * 1024) ?? '');
