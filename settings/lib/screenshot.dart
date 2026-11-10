// F12: a picture of this window, for telling what is wrong (as in Maprisma Playground and the
// author's Omarchy panels). The picture goes to ~/Pictures/<App>/<slug>-<date>-<time>.png (never
// over an older picture or note); the window then names the file and takes an optional note,
// written next to it as a .txt with the picture's name. Nothing is uploaded and no other program
// is started: the window draws itself into the picture.

import 'dart:convert';
import 'dart:io';

import 'private_files.dart';

/// Characters of a note: a few sentences, not a document.
const screenshotNoteLimit = 4000;

String _normalize(String path) {
  final parts = <String>[];
  for (final part in path.split('/')) {
    if (part.isEmpty || part == '.') continue;
    if (part == '..') {
      if (parts.isNotEmpty) parts.removeLast();
    } else {
      parts.add(part);
    }
  }
  return '/${parts.join('/')}';
}

/// The pictures folder: XDG_PICTURES_DIR from user-dirs.dirs ("$HOME/…" or an absolute path;
/// "$HOME" alone is no pictures folder of its own), else ~/Pictures. user-dirs.dirs is read only
/// as a regular file (no link, FIFO or device) of at most 64 KiB.
String picturesFolder([Map<String, String>? environment]) {
  final env = environment ?? Platform.environment;
  final home = env['HOME'] ?? '/';
  final configured = env['XDG_CONFIG_HOME'];
  final config = configured != null && configured.startsWith('/') ? configured : '$home/.config';
  var pictures = '$home/Pictures';
  final text = readRegularNoFollow('$config/user-dirs.dirs', maxBytes: 64 * 1024);
  for (final line in const LineSplitter().convert(text)) {
    final match = RegExp(r'^\s*XDG_PICTURES_DIR\s*=\s*"([^"]*)"\s*$').firstMatch(line);
    if (match == null) continue;
    final value = match[1]!.replaceFirst(RegExp(r'^\$HOME(?=/|$)'), home);
    if (value.startsWith('/') && _normalize(value) != _normalize(home)) pictures = _normalize(value);
  }
  return pictures;
}

/// `<pictures>/<app>`: where this app's screenshots go.
String screenshotFolder(String app, [Map<String, String>? environment]) => '${picturesFolder(environment)}/$app';

/// `<date>-<time>` of a screenshot's name: 20261110-120000.
String screenshotStamp(DateTime at) {
  String two(int n) => n.toString().padLeft(2, '0');
  return '${at.year.toString().padLeft(4, '0')}${two(at.month)}${two(at.day)}-'
      '${two(at.hour)}${two(at.minute)}${two(at.second)}';
}

/// `<slug>-<stamp>.png`, or -2, -3 … when a picture or a note already has that name in the
/// folder (also a link that points nowhere).
String freeScreenshotName(PrivateFolder folder, String slug, String stamp) {
  var name = '$slug-$stamp.png';
  var n = 2;
  while (folder.taken(name) || folder.taken('${name.substring(0, name.length - 4)}.txt')) {
    name = '$slug-$stamp-$n.png';
    n++;
  }
  return name;
}

/// The PNG into a new file of its own (0600) in the private folder; returns its path.
String saveScreenshot(String folder, String slug, List<int> png, {DateTime? at}) {
  final where = PrivateFolder.open(folder);
  try {
    final name = freeScreenshotName(where, slug, screenshotStamp(at ?? DateTime.now()));
    where.writeNew(name, png);
    return '$folder/$name';
  } finally {
    where.close();
  }
}

/// The note next to the picture (same name, .txt), at most [screenshotNoteLimit] characters;
/// no text, no file. The folder is checked again and the picture must still be there.
String? saveScreenshotNote(String picture, String text) {
  var note = text.trim();
  if (note.isEmpty) return null;
  final runes = note.runes.toList();
  if (runes.length > screenshotNoteLimit) note = String.fromCharCodes(runes.take(screenshotNoteLimit));
  final slash = picture.lastIndexOf('/');
  final folder = picture.substring(0, slash), name = picture.substring(slash + 1);
  if (!name.endsWith('.png')) throw ArgumentError.value(picture, 'picture', 'not a screenshot');
  final where = PrivateFolder.open(folder);
  try {
    if (!where.hasFile(name)) throw FileSystemException('the picture is gone', picture);
    final txt = '${name.substring(0, name.length - 4)}.txt';
    where.writeNew(txt, utf8.encode('$note\n'));
    return '$folder/$txt';
  } finally {
    where.close();
  }
}

/// The path as the window shows it: the home folder as ~.
String homeShort(String path, [Map<String, String>? environment]) {
  final home = (environment ?? Platform.environment)['HOME'];
  if (home == null || home.isEmpty || home == '/') return path;
  return path == home || path.startsWith('$home/') ? '~${path.substring(home.length)}' : path;
}
