import unittest
from unittest.mock import Mock
import numpy as np
from kokoro_compat import FloatSpeedSession, create


class KokoroCompatTests(unittest.TestCase):
    def test_speed_reaches_model_as_float32(self):
        session = Mock()
        wrapped = FloatSpeedSession(session)
        wrapped.speed = 1.25
        # kokoro-onnx 0.4.7 builds this int32 array for input_ids exports.
        wrapped.run(None, {'input_ids': [[0, 1, 0]], 'speed': np.array([1.25], dtype=np.int32)})
        speed = session.run.call_args.args[1]['speed']
        self.assertEqual(speed.dtype, np.float32)
        self.assertAlmostEqual(float(speed[0]), 1.25)

    def test_create_sets_requested_speed(self):
        model = Mock()
        model.sess = FloatSpeedSession(Mock())
        create(model, 'Hallo.', 'martin', 0.8, 'de')
        self.assertAlmostEqual(model.sess.speed, 0.8)
        model.create.assert_called_once_with('Hallo.', voice='martin', speed=0.8, lang='de')
