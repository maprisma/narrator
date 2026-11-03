"""Reusable, cancellable worker subprocesses (Kokoro speech, translation) owned by the reader."""
import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer


class SpeechWorker(QObject):
    def __init__(self, owner, script='kokoro_tts.py', label='Speech'):
        super().__init__(owner)
        self.owner, self.label = owner, label
        self.pending = None
        self.buffer = b''
        self.proc = QProcess(self)
        self.proc.setProgram(sys.executable)
        self.proc.setArguments([str(Path(__file__).with_name(script)), '--worker'])
        self.proc.readyReadStandardOutput.connect(self.receive)
        self.proc.readyReadStandardError.connect(self.drain_errors)
        self.proc.finished.connect(self.exited)
        self.proc.errorOccurred.connect(self.error)

    def request(self, payload, done):
        if self.pending is not None:
            raise RuntimeError(self.label + ' worker is busy')
        request = SpeechRequest(self, done)
        self.pending = request
        if self.proc.state() == QProcess.ProcessState.NotRunning:
            self.buffer = b''
            self.proc.start()
        self.proc.write((json.dumps(payload) + '\n').encode())
        return request

    def receive(self):
        self.buffer += bytes(self.proc.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if self.pending is None:
                continue
            try:
                result = json.loads(line)
                self.pending.finish(result['code'], result['error'], output=str(result.get('text', '')))
            except (ValueError, KeyError, TypeError):
                self.pending.finish(1, 'Invalid ' + self.label.lower() + ' worker reply')

    def drain_errors(self):
        self.proc.readAllStandardError()

    def exited(self, *_):
        if self.pending is not None:
            self.pending.finish(1, self.label + ' worker exited before finishing')

    def error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.exited()

    def close(self):
        if self.pending is not None:
            self.pending.cancel()
        self.proc.kill()
        self.proc.waitForFinished(1000)


class SpeechRequest(QObject):
    def __init__(self, worker, done):
        super().__init__(worker)
        self.worker, self.done = worker, done
        worker.owner.tasks.add(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.expire)
        self.timer.start(180000)

    @property
    def proc(self):
        return self.worker.proc

    def finish(self, code, error, cancelled=False, output=''):
        if self.worker.pending is not self:
            return
        self.timer.stop()
        self.worker.pending = None
        self.worker.owner.tasks.discard(self)
        self.worker.owner.speech_tasks.discard(self)
        if not cancelled:
            self.done(code, output, error)
        self.deleteLater()

    def cancel(self):
        self.finish(1, '', cancelled=True)
        # Reap before reusing output slots or starting another request.
        self.worker.proc.kill()
        self.worker.proc.waitForFinished(1000)

    def expire(self):
        self.worker.proc.kill()
        self.worker.proc.waitForFinished(1000)
        self.finish(1, self.worker.label + ' timed out')
