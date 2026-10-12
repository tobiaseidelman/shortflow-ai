from types import SimpleNamespace
import wave
from app import narration


def test_long_sentence_reaches_voice_intact_and_audio_matches_captions(tmp_path, monkeypatch):
    import piper
    spoken = []
    sentence = ('Mi hermano quería que pagara toda la comida de su boda pero cuando le pregunté '
                'si podía llevar a mi pareja me explicó que ni siquiera había reservado un lugar para mí.')
    def synthesize(text, syn_config):
        assert syn_config.length_scale == .93
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


def test_caption_silence_and_punctuation():
    import numpy as np
    raw=np.concatenate([np.zeros(2205),np.full(22050,2000),np.zeros(4410)]).astype('<i2').tobytes()
    start,end=narration.speech_bounds(raw,22050)
    assert .08 <= start <= .1
    assert 1.1 <= end <= 1.12
    assert narration.caption_groups('Mi madre dijo: no vuelvas, por favor.') == ['Mi madre dijo:', 'no vuelvas,', 'por favor.']


def test_paragraph_pause_is_in_audio_and_caption_clock(tmp_path,monkeypatch):
    import piper
    def synthesize(text,syn_config):
        yield SimpleNamespace(audio_int16_bytes=b'\x01\x00'*22050)
    monkeypatch.setattr(narration,'ensure_voice',lambda _:tmp_path/'voice.onnx')
    monkeypatch.setattr(piper.PiperVoice,'load',lambda _:SimpleNamespace(config=SimpleNamespace(sample_rate=22050),synthesize=synthesize))
    audio,captions,duration=narration.narrate('Mi hermano llegó.\n\nMi madre esperó.',tmp_path/'out',tmp_path,lambda _:None)
    assert abs(duration-2.16)<.001
    with wave.open(str(audio)) as f:
        f.setpos(22050)
        assert f.readframes(3528)==b'\0\0'*3528
    assert '0:00:01.16' in captions.read_text()


def test_intro_card_is_spoken_once_and_story_starts_after_it(tmp_path, monkeypatch):
    import piper
    spoken=[]
    def synthesize(text,syn_config):
        spoken.append(text)
        yield SimpleNamespace(audio_int16_bytes=b'\x01\x00'*22050)
    monkeypatch.setattr(narration,'ensure_voice',lambda _:tmp_path/'voice.onnx')
    monkeypatch.setattr(piper.PiperVoice,'load',lambda _:SimpleNamespace(config=SimpleNamespace(sample_rate=22050),synthesize=synthesize))
    audio,captions,duration=narration.narrate('Mi hermano llegó.',tmp_path/'out',tmp_path,lambda _:None,intro='Le presté mi auto. Lo puso en venta.')
    assert spoken==['Le presté mi auto. Lo puso en venta.', 'Mi hermano llegó.']
    assert abs(duration-2.24)<.001
    contents=captions.read_text()
    assert '0:00:01.00,Card' in contents
    assert '0:00:01.24,' in contents
    assert 'SHORTFLOW · RELATO' in contents
    assert 'Default,,0,0,0,,Le presté' not in contents
