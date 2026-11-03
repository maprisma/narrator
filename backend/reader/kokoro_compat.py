"""Load Kokoro models with a fix for kokoro-onnx 0.4.x on newer model exports.

kokoro-onnx 0.4.4–0.4.7 sends the speed input as int32 to exports that take
`input_ids` (the standard v1.0 model), which expect float32. ONNX Runtime then
rejects every request, so only the German Martin export worked on fresh installs.
"""
import numpy as np


class FloatSpeedSession:
    """Pass the requested speed to the model as float32."""
    def __init__(self, session):
        self.session = session
        self.speed = 1.0

    def run(self, names, inputs, *args, **kwargs):
        if 'speed' in inputs:
            inputs = dict(inputs, speed=np.array([self.speed], dtype=np.float32))
        return self.session.run(names, inputs, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.session, name)


def load(model_path, voices_path):
    from kokoro_onnx import Kokoro
    model = Kokoro(str(model_path), str(voices_path))
    model.sess = FloatSpeedSession(model.sess)
    return model


def create(model, text, voice, speed=1.0, lang='en-us', is_phonemes=False):
    if isinstance(model.sess, FloatSpeedSession):
        model.sess.speed = float(speed)
    if is_phonemes:
        return model.create(text, voice=voice, speed=speed, lang=lang, is_phonemes=True)
    return model.create(text, voice=voice, speed=speed, lang=lang)


_JAPANESE = []


def japanese_phonemes(text):
    """Kanji-aware Japanese phonemes (misaki + UniDic); espeak reads kanji as 'Chinese letter'."""
    if not _JAPANESE:
        from misaki import ja
        _JAPANESE.append(ja.JAG2P())
    result = _JAPANESE[0](text)
    return result[0] if isinstance(result, tuple) else result
