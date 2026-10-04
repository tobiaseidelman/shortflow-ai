from types import SimpleNamespace
import wave
from app import narration


def test_long_sentence_reaches_voice_intact_and_audio_matches_captions(tmp_path, monkeypatch):
    import piper
    spoken = []
    sentence = ('Mi hermano quería que pagara toda la comida de su boda pero cuando le pregunté '
                'si podía llevar a mi pareja me explicó que ni siquiera había reservado un lugar para mí.')
    def synthesize(text, syn_config):
        spoken.append(text)
        yield SimpleNamespace(audio_int16_bytes=b'\x01\x00' * 22050)
    monkeypatch.setattr(narration, 'ensure_voice', lambda _: tmp_path/'voice.onnx')
    monkeypatch.setattr(piper.PiperVoice, 'load', lambda _: SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050), synthesize=synthesize))
    audio, captions, duration = narration.narrate(sentence+'\nDecidí llamarlo.', tmp_path/'output', tmp_path, lambda _: None)
    assert spoken == [sentence, 'Decidí llamarlo.']
    with wave.open(str(audio)) as f:
        assert f.getnframes()/f.getframerate() == duration
    assert abs(duration-2) < .001
    assert '0:00:02.00' in captions.read_text()
