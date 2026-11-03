import unittest
from PySide6.QtCore import QCoreApplication, QObject
from speech_worker import SpeechWorker


class SpeechWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.owner = QObject()
        self.owner.tasks = set()
        self.owner.speech_tasks = set()
        self.worker = SpeechWorker(self.owner)
        self.worker.proc.setArguments(['-u', '-c',
            'import sys,json,time\nfor line in sys.stdin:\n r=json.loads(line); time.sleep(r.get("delay",0)); print(json.dumps({"code":0,"error":""}),flush=True)'])

    def tearDown(self):
        self.worker.close()

    def complete(self, results):
        import time
        deadline = time.monotonic() + 5
        while not results and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.001)
        self.assertTrue(results)

    def test_multiple_requests_reuse_process(self):
        first = []
        self.worker.request({}, lambda *args: first.append(args))
        self.complete(first)
        pid = self.worker.proc.processId()
        second = []
        self.worker.request({}, lambda *args: second.append(args))
        self.complete(second)
        self.assertEqual(pid, self.worker.proc.processId())
        self.assertEqual(first[0][0], 0)
        self.assertFalse(self.owner.tasks)

    def test_cancelled_request_cannot_deliver_stale_audio(self):
        stale = []
        request = self.worker.request({'delay': 30}, lambda *args: stale.append(args))
        request.cancel()
        fresh = []
        self.worker.request({}, lambda *args: fresh.append(args))
        self.complete(fresh)
        self.assertEqual(stale, [])
        self.assertEqual(fresh[0][0], 0)
