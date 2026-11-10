import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:maprisma_narrator/private_files.dart';
import 'package:maprisma_narrator/screenshot.dart';

void main() {
  late Directory tmp;
  setUp(() => tmp = Directory.systemTemp.createTempSync('shot-test-'));
  tearDown(() {
    debugFailWriteAfter = null;
    tmp.deleteSync(recursive: true);
  });

  Map<String, String> env() => {'HOME': tmp.path, 'XDG_CONFIG_HOME': '${tmp.path}/cfg'};
  void userDirs(String text) => (File('${tmp.path}/cfg/user-dirs.dirs')..createSync(recursive: true)).writeAsStringSync(text);
  int mode(String path) => FileStat.statSync(path).mode & 0x1ff;

  group('pictures folder', () {
    test('without user-dirs.dirs: ~/Pictures', () {
      expect(picturesFolder(env()), '${tmp.path}/Pictures');
      expect(screenshotFolder('Maprisma Narrator', env()), '${tmp.path}/Pictures/Maprisma Narrator');
    });
    test(r'"$HOME/…" and absolute values', () {
      userDirs('XDG_PICTURES_DIR="\$HOME/Bilder"\n');
      expect(picturesFolder(env()), '${tmp.path}/Bilder');
      userDirs('# x\nXDG_PICTURES_DIR="/srv/pics/"\n');
      expect(picturesFolder(env()), '/srv/pics');
    });
    test(r'"$HOME" alone and relative values are no pictures folder', () {
      userDirs('XDG_PICTURES_DIR="\$HOME"\n');
      expect(picturesFolder(env()), '${tmp.path}/Pictures');
      userDirs('XDG_PICTURES_DIR="Bilder"\n');
      expect(picturesFolder(env()), '${tmp.path}/Pictures');
    });
    test('a linked, oversized or FIFO user-dirs.dirs is not read', () {
      final real = File('${tmp.path}/real')..writeAsStringSync('XDG_PICTURES_DIR="\$HOME/Bilder"\n');
      Directory('${tmp.path}/cfg').createSync();
      Link('${tmp.path}/cfg/user-dirs.dirs').createSync(real.path);
      expect(picturesFolder(env()), '${tmp.path}/Pictures');
      File('${tmp.path}/cfg/user-dirs.dirs').deleteSync();
      userDirs('XDG_PICTURES_DIR="\$HOME/Bilder"\n${'#' * (64 * 1024)}\n');
      expect(picturesFolder(env()), '${tmp.path}/Pictures');
      File('${tmp.path}/cfg/user-dirs.dirs').deleteSync();
      expect(Process.runSync('mkfifo', ['${tmp.path}/cfg/user-dirs.dirs']).exitCode, 0);
      expect(picturesFolder(env()), '${tmp.path}/Pictures'); // and it did not block
    });
  });

  group('private folder', () {
    test('made 0700 when missing, with its parents', () {
      final where = '${tmp.path}/Pictures/App';
      PrivateFolder.open(where).close();
      expect(FileSystemEntity.isDirectorySync(where), isTrue);
      expect(mode(where), 0x1c0);
    });
    test('a link to a folder is refused', () {
      Directory('${tmp.path}/real').createSync();
      Link('${tmp.path}/App').createSync('${tmp.path}/real');
      expect(() => PrivateFolder.open('${tmp.path}/App'), throwsA(isA<FileSystemException>()));
    });
    test('a folder others can write to is refused', () {
      final where = Directory('${tmp.path}/App')..createSync();
      Process.runSync('chmod', ['775', where.path]);
      expect(() => PrivateFolder.open(where.path), throwsA(isA<FileSystemException>()));
      Process.runSync('chmod', ['757', where.path]);
      expect(() => PrivateFolder.open(where.path), throwsA(isA<FileSystemException>()));
    });
  });

  group('files', () {
    final at = DateTime(2026, 11, 10, 9, 5, 7);
    test('<slug>-<date>-<time>.png, 0600, then -2 and -3 (also for a note or a dead link)', () {
      final where = '${tmp.path}/App';
      final first = saveScreenshot(where, 'maprisma-narrator', [1, 2, 3], at: at);
      expect(first, '$where/maprisma-narrator-20261110-090507.png');
      expect(File(first).readAsBytesSync(), [1, 2, 3]);
      expect(mode(first), 0x180);
      File('$where/maprisma-narrator-20261110-090507-2.txt').writeAsStringSync('old note');
      expect(saveScreenshot(where, 'maprisma-narrator', [4], at: at), '$where/maprisma-narrator-20261110-090507-3.png');
      Link('$where/maprisma-narrator-20261110-090507-4.png').createSync('${tmp.path}/nowhere');
      expect(saveScreenshot(where, 'maprisma-narrator', [5], at: at), '$where/maprisma-narrator-20261110-090507-5.png');
      expect(File('$where/maprisma-narrator-20261110-090507-2.txt').readAsStringSync(), 'old note');
    });
    test('never over an existing file', () {
      final folder = PrivateFolder.open('${tmp.path}/App');
      try {
        folder.writeNew('a.png', [1]);
        expect(() => folder.writeNew('a.png', [2]), throwsA(isA<FileSystemException>()));
        expect(File('${tmp.path}/App/a.png').readAsBytesSync(), [1]);
      } finally {
        folder.close();
      }
    });
    test('a failed write leaves nothing behind', () {
      debugFailWriteAfter = 3;
      expect(() => saveScreenshot('${tmp.path}/App', 'app', List.filled(100, 7), at: at),
          throwsA(isA<FileSystemException>()));
      expect(Directory('${tmp.path}/App').listSync(), isEmpty);
    });
    test('short writes go on; a write of 0 bytes fails', () {
      final seen = <int>[];
      writeFully(10, (offset, count) {
        seen.add(offset);
        return 3 < count ? 3 : count;
      }, where: 'x');
      expect(seen, [0, 3, 6, 9]);
      expect(() => writeFully(10, (offset, count) => offset == 0 ? 4 : 0, where: 'x'),
          throwsA(isA<FileSystemException>()));
    });
  });

  group('note', () {
    test('next to the picture, at most 4000 characters; no text, no file', () {
      final picture = saveScreenshot('${tmp.path}/App', 'app', [1], at: DateTime(2026));
      expect(saveScreenshotNote(picture, '  \n '), isNull);
      expect(File(picture.replaceFirst('.png', '.txt')).existsSync(), isFalse);
      final note = saveScreenshotNote(picture, ' ${'ä' * 5000} ')!;
      expect(note, picture.replaceFirst('.png', '.txt'));
      expect(utf8.decode(File(note).readAsBytesSync()), '${'ä' * 4000}\n');
      expect(mode(note), 0x180);
      expect(() => saveScreenshotNote(picture, 'again'), throwsA(isA<FileSystemException>()));
    });
    test('not when the picture is gone', () {
      final picture = saveScreenshot('${tmp.path}/App', 'app', [1], at: DateTime(2026));
      File(picture).deleteSync();
      expect(() => saveScreenshotNote(picture, 'x'), throwsA(isA<FileSystemException>()));
    });
    test('the home folder is shown as ~', () {
      expect(homeShort('/home/u/Pictures/a.png', {'HOME': '/home/u'}), '~/Pictures/a.png');
      expect(homeShort('/home/user2/a.png', {'HOME': '/home/u'}), '/home/user2/a.png');
    });
  });
}
