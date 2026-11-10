// Private files for F12's screenshots (as Maprisma Playground's private_files.dart): libc gives
// the guarantees dart:io cannot express (O_NOFOLLOW, O_EXCL, 0600 from the first byte, files made
// relative to a checked folder handle). Linux only.

import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';

final _libc = DynamicLibrary.open('libc.so.6');
final _malloc = _libc.lookupFunction<Pointer<Void> Function(IntPtr), Pointer<Void> Function(int)>('malloc');
final _free = _libc.lookupFunction<Void Function(Pointer<Void>), void Function(Pointer<Void>)>('free');
final _open = _libc
    .lookupFunction<Int32 Function(Pointer<Uint8>, Int32, Int32), int Function(Pointer<Uint8>, int, int)>('open');
final _openAt = _libc.lookupFunction<
  Int32 Function(Int32, Pointer<Uint8>, Int32, Uint32),
  int Function(int, Pointer<Uint8>, int, int)
>('openat');
final _unlinkAt = _libc
    .lookupFunction<Int32 Function(Int32, Pointer<Uint8>, Int32), int Function(int, Pointer<Uint8>, int)>('unlinkat');
final _read = _libc
    .lookupFunction<IntPtr Function(Int32, Pointer<Uint8>, IntPtr), int Function(int, Pointer<Uint8>, int)>('read');
final _write = _libc
    .lookupFunction<IntPtr Function(Int32, Pointer<Uint8>, IntPtr), int Function(int, Pointer<Uint8>, int)>('write');
final _fsync = _libc.lookupFunction<Int32 Function(Int32), int Function(int)>('fsync');
final _close = _libc.lookupFunction<Int32 Function(Int32), int Function(int)>('close');
final _mkdir = _libc.lookupFunction<Int32 Function(Pointer<Uint8>, Uint32), int Function(Pointer<Uint8>, int)>('mkdir');
final _getuid = _libc.lookupFunction<Uint32 Function(), int Function()>('getuid');
final _statx = _libc.lookupFunction<
  Int32 Function(Int32, Pointer<Uint8>, Int32, Uint32, Pointer<Uint8>),
  int Function(int, Pointer<Uint8>, int, int, Pointer<Uint8>)
>('statx');
final _errnoLocation = _libc.lookupFunction<Pointer<Int32> Function(), Pointer<Int32> Function()>('__errno_location');
final _strerror = _libc.lookupFunction<Pointer<Uint8> Function(Int32), Pointer<Uint8> Function(int)>('strerror');

const _oWronly = 0x1, _oCreat = 0x40, _oExcl = 0x80, _oNonblock = 0x800;
const _oDirectory = 0x10000, _oNofollow = 0x20000, _oCloexec = 0x80000;
const _atFdcwd = -100, _atSymlinkNofollow = 0x100, _atEmptyPath = 0x1000;
const _sIfmt = 0xf000, _sIfdir = 0x4000, _sIfreg = 0x8000;

Pointer<Uint8> _allocate(int bytes) {
  final ptr = _malloc(bytes < 1 ? 1 : bytes).cast<Uint8>();
  if (ptr.address == 0) throw const OSError('Cannot allocate memory', 12);
  return ptr;
}

Pointer<Uint8> _text(String text) {
  final bytes = utf8.encode(text);
  if (bytes.contains(0)) throw ArgumentError.value(text, 'path', 'contains a NUL byte');
  final ptr = _allocate(bytes.length + 1);
  ptr.asTypedList(bytes.length + 1)
    ..setAll(0, bytes)
    ..[bytes.length] = 0;
  return ptr;
}

/// The last libc error as an OSError (its own English text).
OSError _lastError() {
  final code = _errnoLocation().value;
  final text = _strerror(code);
  var length = 0;
  while (text[length] != 0) {
    length++;
  }
  return OSError(utf8.decode(text.asTypedList(length), allowMalformed: true), code);
}

int get fileOwnerUid => _getuid();

/// uid and mode of a file (statx; no link followed), or of an open descriptor when [path] is
/// empty; null when it is not there.
({int uid, int mode})? _identity(String path, {int fd = _atFdcwd}) {
  final name = _text(path), buffer = _allocate(256);
  try {
    final flags = (path.isEmpty ? _atEmptyPath : 0) | _atSymlinkNofollow;
    if (_statx(fd, name, flags, 0x7ff, buffer) != 0) return null;
    final b = buffer.asTypedList(256).buffer.asByteData();
    return (uid: b.getUint32(20, Endian.host), mode: b.getUint16(28, Endian.host));
  } finally {
    _free(name.cast());
    _free(buffer.cast());
  }
}

/// A bounded read of a regular file that follows no final link and never blocks on a FIFO
/// (O_NOFOLLOW|O_NONBLOCK; the opened descriptor must be a regular file); '' otherwise or when it
/// is larger than [maxBytes].
String readRegularNoFollow(String path, {int maxBytes = 64 * 1024}) {
  final name = _text(path);
  int fd;
  try {
    fd = _open(name, _oNofollow | _oNonblock | _oCloexec, 0);
  } finally {
    _free(name.cast());
  }
  if (fd < 0) return '';
  final buffer = _allocate(maxBytes + 1);
  try {
    final info = _identity('', fd: fd);
    if (info == null || info.mode & _sIfmt != _sIfreg) return '';
    var total = 0;
    while (total <= maxBytes) {
      final count = _read(fd, buffer + total, maxBytes + 1 - total);
      if (count < 0) return '';
      if (count == 0) break;
      total += count;
    }
    return total > maxBytes ? '' : utf8.decode(buffer.asTypedList(total), allowMalformed: true);
  } finally {
    _close(fd);
    _free(buffer.cast());
  }
}

/// Writes [length] bytes with [write] (offset, count → bytes written): a short write goes on with
/// the rest, a write that returns 0 or less fails.
void writeFully(int length, int Function(int offset, int count) write, {required String where}) {
  var offset = 0;
  while (offset < length) {
    final n = write(offset, length - offset);
    if (n <= 0) {
      throw FileSystemException('write', where, n < 0 ? _lastError() : const OSError('Nothing was written', 5));
    }
    offset += n;
  }
}

/// Tests only: a write of a new file fails after this many bytes (a full disk, an I/O error).
int? debugFailWriteAfter;

/// A handle on a folder of this account's that only it may write to: made 0700 when missing; used
/// only when it is a real folder (opened with O_DIRECTORY|O_NOFOLLOW, so no link), owned by this
/// account and not writable by group or others (checked on the opened handle). Files are made
/// relative to that handle, so the folder cannot be swapped between the check and the write.
final class PrivateFolder {
  PrivateFolder._(this.path, this._fd);

  factory PrivateFolder.open(String path) {
    Directory(File(path).parent.path).createSync(recursive: true);
    final name = _text(path);
    int fd;
    try {
      if (_mkdir(name, 0x1c0) != 0) {
        final error = _lastError();
        if (error.errorCode != 17) throw FileSystemException('mkdir', path, error); // EEXIST is fine
      }
      fd = _open(name, _oDirectory | _oNofollow | _oCloexec, 0);
    } finally {
      _free(name.cast());
    }
    if (fd < 0) throw FileSystemException('not a private folder of yours', path, _lastError());
    final info = _identity('', fd: fd);
    if (info == null || info.mode & _sIfmt != _sIfdir || info.uid != fileOwnerUid || info.mode & 0x12 != 0) {
      _close(fd);
      throw FileSystemException('not a private folder of yours', path, const OSError('Permission denied', 13));
    }
    return PrivateFolder._(path, fd);
  }

  final String path;
  int _fd;

  static void _plain(String name) {
    if (name.isEmpty || name == '.' || name == '..' || name.contains('/')) {
      throw ArgumentError.value(name, 'name', 'not a plain file name');
    }
  }

  /// Something of that name is in the folder (also a link that points nowhere).
  bool taken(String name) {
    _plain(name);
    return _identity(name, fd: _fd) != null;
  }

  /// A regular file of that name is in the folder (no link followed).
  bool hasFile(String name) {
    _plain(name);
    final info = _identity(name, fd: _fd);
    return info != null && info.mode & _sIfmt == _sIfreg;
  }

  /// A new file of our own in the folder (0600, never through a link, never over an existing
  /// file), written completely and synced, or removed again.
  void writeNew(String name, List<int> bytes) {
    _plain(name);
    final where = '$path/$name';
    final cName = _text(name);
    try {
      final out = _openAt(_fd, cName, _oWronly | _oCreat | _oExcl | _oNofollow | _oCloexec, 0x180);
      if (out < 0) throw FileSystemException('open', where, _lastError());
      final buffer = _allocate(bytes.length);
      var ok = false;
      try {
        buffer.asTypedList(bytes.length).setAll(0, bytes);
        writeFully(bytes.length, (offset, count) {
          final limit = debugFailWriteAfter;
          if (limit != null) {
            if (offset >= limit) return 0;
            count = count.clamp(1, limit - offset);
          }
          return _write(out, buffer + offset, count);
        }, where: where);
        if (_fsync(out) != 0) throw FileSystemException('fsync', where, _lastError());
        ok = true;
      } finally {
        _free(buffer.cast());
        _close(out);
        if (!ok) _unlinkAt(_fd, cName, 0); // nothing half-written is left behind
      }
    } finally {
      _free(cName.cast());
    }
  }

  void close() {
    if (_fd >= 0) {
      _close(_fd);
      _fd = -1;
    }
  }
}
