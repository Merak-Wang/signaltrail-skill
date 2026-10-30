"""Behavior checks for reusable, bounded local narration."""
import shutil
import wave
from pathlib import Path

import pytest

from signaltrail import voice_synthesis


def test_sentence_boundaries_preserve_abbreviations_and_decimals():
    text = 'Dr. Chen works in the U.S. market. Revenue rose 3.5%. 下一句。'
    assert voice_synthesis.narration_sentences(text) == [
        'Dr. Chen works in the U.S. market.', 'Revenue rose 3.5%.', '下一句。']


def _runtime(tmp_path):
    model = tmp_path / 'model'
    model.mkdir()
    for name in ('encoder.onnx', 'decoder.onnx', 'vocos_24khz.onnx',
                 'tokens.txt', 'lexicon.txt', 'lexicon-en-us-zipvoice.txt'):
        (model / name).touch()
    executable = tmp_path / 'tts'
    executable.touch()
    reference = tmp_path / 'reference.wav'
    _write(reference, .1)
    return {'model_dir': model, 'tts_executable': executable, 'provider': 'cpu',
            'ffmpeg': 'ffmpeg', 'voice_profile': {
                'name': 'reference', 'engine': 'zipvoice', 'speed': .9,
                'reference_id': 'neutral', 'references': [
                    {'id': 'neutral', 'audio': str(reference), 'text': '参考文字。'}]}}


def _write(path, seconds, full_scale=False):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        stream.writeframes((b'\xff\x7f' if full_scale else b'\xe8\x03')
                           + b'\xe8\x03' * (round(seconds * 8000) - 1))


def test_same_sentences_reuse_audio_across_page_reordering(tmp_path, monkeypatch):
    runtime, calls = _runtime(tmp_path), []

    def native(arguments):
        output = next((a.split('=', 1)[1] for a in arguments
                       if a.startswith('--output-filename=')), None)
        if output:
            calls.append(arguments)
            _write(Path(output), .2, full_scale=len(calls) == 1)
        else:
            shutil.copyfile(runtime['voice_profile']['references'][0]['audio'], arguments[-1])

    monkeypatch.setattr(voice_synthesis, 'run_native', native)
    voice = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    first = voice.page('Title', 'First sentence. Second sentence.', tmp_path / 'first.wav')
    assert first['full_scale_samples'] == 1
    assert first['full_scale_fraction'] == pytest.approx(1 / first['sample_count'])
    assert first['gain_db'] < 0
    count = len(calls)
    second_voice = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    second = second_voice.page('Title', 'Second sentence. First sentence.', tmp_path / 'second.wav')
    assert len(calls) == count == 3
    assert second_voice.hits == 3
    assert first['duration'] == pytest.approx(second['duration'])
    assert [s['text'] for s in second['segments']] == [
        'Title', 'Second sentence.', 'First sentence.']
    runtime['voice_profile']['pauses'] = {'title': .8}
    runtime['voice_profile']['gain_db'] = 2
    changed_playback = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    adjusted = changed_playback.page(
        'Title', 'First sentence. Second sentence.', tmp_path / 'adjusted.wav')
    assert len(calls) == 3
    assert adjusted['duration'] > first['duration']
    config = next((tmp_path / 'cache').rglob('reference.conf'))
    assert '参考文字。' in config.read_text(encoding='utf-8')
    assert '--speed=0.9' in calls[0]
    assert str(runtime['model_dir'] / 'lexicon-en-us-zipvoice.txt') in next(
        value for value in calls[0] if value.startswith('--zipvoice-lexicon='))


def test_long_page_keeps_original_speed_without_duration_limit(tmp_path, monkeypatch):
    runtime, calls = _runtime(tmp_path), []

    def native(arguments):
        output = next((a.split('=', 1)[1] for a in arguments
                       if a.startswith('--output-filename=')), None)
        if output:
            calls.append(arguments)
            _write(Path(output), 31 if arguments[-1] == 'Long sentence.' else .1)
        else:
            shutil.copyfile(runtime['voice_profile']['references'][0]['audio'], arguments[-1])

    monkeypatch.setattr(voice_synthesis, 'run_native', native)
    voice = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    result = voice.page('Title', 'Long sentence.', tmp_path / 'output.wav')
    assert len(calls) == 2
    assert all('--speed=0.9' in arguments for arguments in calls)
    assert result['duration'] > 28
    assert result['tempo'] == 1.08


def test_spoken_copy_preserves_display_and_name_boundaries():
    assert voice_synthesis.spoken_narration(
        'OpenAI rose 3.5%, while MyOpenAI stayed flat.', 'en',
        {'OpenAI': 'Open A I'}) == (
            'Open A I rose three point five percent, while MyOpenAI stayed flat.')


def _qwen_runtime(tmp_path):
    runtime = _runtime(tmp_path)
    runtime['voice_profile'].update(engine='qwen3', gain_db=0, peak_limit=.794)
    for key in ('model_path', 'mmproj_path'):
        runtime[key] = runtime['model_dir'] / (key + '.gguf')
        runtime[key].touch()
    return runtime


def test_qwen_gpu_failure_retries_whole_page_on_cpu_and_reuses_cache(tmp_path, monkeypatch):
    from signaltrail import video_runtime

    runtime = _qwen_runtime(tmp_path)
    runtime.update(provider='cuda', device_name='CUDA0')
    calls = []

    def native(arguments, **kwargs):
        calls.append(arguments)
        output = Path(arguments[arguments.index('--output') + 1])
        _write(output, .2)
        output.with_suffix('.log').write_text('generated 2 frames', encoding='utf-8')
        if '--mmproj-device' in arguments:
            raise voice_synthesis.NativeInferenceError('CUDA out of memory')

    monkeypatch.setattr(voice_synthesis, 'run_native', native)
    monkeypatch.setattr(video_runtime, 'cpu_video_runtime',
                        lambda value: value | {'provider': 'cpu', 'device_name': 'none'},
                        raising=False)
    voice = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    result = voice.page('新闻标题。', '完整句子。', tmp_path / 'first.wav')
    assert result['provider'] == 'cpu'
    assert result['fallback_reason'] == 'CUDA out of memory'
    assert len(calls) == 3
    assert all('--no-mmproj-offload' in command for command in calls[1:])
    assert all(command[command.index('--tts-lang') + 1] == 'zh' for command in calls)
    assert all(Path(command[command.index('-f') + 1]).read_text('utf-8') == '完整句子。'
               for command in calls[-1:])
    voice.page('新闻标题。', '完整句子。', tmp_path / 'second.wav')
    assert len(calls) == 3
    assert voice.hits == 2
    reference = runtime['voice_profile']['references'][0]['audio']
    assert all(command[command.index('--tts-speaker-file') + 1] == reference for command in calls)


def test_qwen_english_has_explicit_language_and_no_duration_limit(tmp_path, monkeypatch):
    calls = []

    def native(arguments, **kwargs):
        calls.append(arguments)
        text = Path(arguments[arguments.index('-f') + 1]).read_text('utf-8')
        output = Path(arguments[arguments.index('--output') + 1])
        _write(output, 31 if 'Long sentence.' in text else .1)
        output.with_suffix('.log').write_text('generated 2 frames', encoding='utf-8')

    monkeypatch.setattr(voice_synthesis, 'run_native', native)
    runtime = _qwen_runtime(tmp_path)
    runtime.update(provider='cuda', device_name='CUDA0')
    voice = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    result = voice.page('Title.', 'Long sentence.', tmp_path / 'output.wav', language='en')
    assert result['duration'] > 28
    assert len(calls) == 2
    assert all(command[command.index('--tts-lang') + 1] == 'en' for command in calls)


def test_qwen_rejects_frame_limit_before_caching(tmp_path, monkeypatch):
    runtime = _qwen_runtime(tmp_path)

    def native(arguments, **kwargs):
        output = Path(arguments[arguments.index('--output') + 1])
        _write(output, .2)
        output.with_suffix('.log').write_text('generated 500 frames', encoding='utf-8')

    monkeypatch.setattr(voice_synthesis, 'run_native', native)
    voice = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    with pytest.raises(ValueError, match='frame limit'):
        voice.page('标题', '短稿。', tmp_path / 'out.wav')
    assert voice.generated == 0
    assert not list(voice.cache.glob('*.wav')) or all(
        path.name.endswith('.pending.wav') for path in voice.cache.glob('*.wav'))


def test_qwen_reuses_existing_sentence_cache(tmp_path, monkeypatch):
    import hashlib

    runtime = _qwen_runtime(tmp_path)
    voice = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    for text in ('标题', '短稿。'):
        key = hashlib.sha256(('zh-CN\0' + text).encode()).hexdigest()[:24]
        _write(voice.cache / f'{key}.wav', .2)
        (voice.cache / f'{key}.log').write_text('generated 2 frames', encoding='utf-8')
    monkeypatch.setattr(voice_synthesis, 'run_native',
                        lambda *args, **kwargs: pytest.fail('unexpected synthesis'))
    result = voice.page('标题', '短稿。', tmp_path / 'output.wav')
    assert len(result['segments']) == 2
    assert voice.hits == 2
    assert voice.generated == 0


def test_page_cache_replays_without_rewriting_and_invalidates_on_changes(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    calls = []

    def native(arguments):
        output = next((a.split('=', 1)[1] for a in arguments
                       if a.startswith('--output-filename=')), None)
        if output:
            calls.append(arguments)
            _write(Path(output), .2)
        else:
            shutil.copyfile(runtime['voice_profile']['references'][0]['audio'], arguments[-1])

    monkeypatch.setattr(voice_synthesis, 'run_native', native)
    destination = tmp_path / 'page.wav'
    voice = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    first = voice.page('Title', 'Text.', destination, language='en')
    manifest = destination.with_suffix('.voice.json')
    original = (destination.stat().st_mtime_ns, manifest.stat().st_mtime_ns)
    replay = voice.page('Title', 'Text.', destination, language='en')
    assert replay['page_cache_hit'] and voice.page_hits == 1
    assert voice.hits == 0 and voice.generated == 2
    assert all(segment['seconds'] == 0 and 'original_seconds' in segment
               for segment in replay['segments'])
    assert (destination.stat().st_mtime_ns, manifest.stat().st_mtime_ns) == original
    runtime['voice_profile']['gain_db'] = 2
    changed = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    assert not changed.page('Title', 'Text.', destination, language='en')['page_cache_hit']
    assert changed.hits == 2 and changed.generated == 0
    assert not changed.page('Title', 'Different.', destination, language='en')['page_cache_hit']
    assert first['spoken_text'] == replay['spoken_text']
    with destination.open('ab') as audio:
        audio.write(b'changed')
    assert not changed.page('Title', 'Different.', destination, language='en')['page_cache_hit']


def test_page_cache_invalidates_when_reference_changes(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)

    def native(arguments):
        output = next((a.split('=', 1)[1] for a in arguments
                       if a.startswith('--output-filename=')), None)
        if output:
            _write(Path(output), .2)
        else:
            shutil.copyfile(runtime['voice_profile']['references'][0]['audio'], arguments[-1])

    monkeypatch.setattr(voice_synthesis, 'run_native', native)
    destination = tmp_path / 'page.wav'
    first = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    first.page('Title', 'Text.', destination, language='en')
    reference = Path(runtime['voice_profile']['references'][0]['audio'])
    _write(reference, .3)
    changed = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    assert not changed.page('Title', 'Text.', destination, language='en')['page_cache_hit']
    assert changed.generated == 2


def test_long_silence_shortening_preserves_speech_and_normal_pauses(tmp_path):
    import array

    sample = tmp_path / 'format.wav'
    _write(sample, .1)
    with wave.open(str(sample)) as stream:
        params = stream.getparams()
    rate = params.framerate
    speech = array.array('h', [1000] * (rate // 2))
    short = array.array('h', [0] * (rate // 2))
    long = array.array('h', [10] * (rate * 2))
    original = speech + short + speech + long + speech
    result, removed = voice_synthesis._shorten_long_silences(original, params)
    assert removed == pytest.approx(1.3, abs=.03)
    assert result[:len(speech) + len(short) + len(speech)] == (speech + short + speech)
    assert result[-len(speech):] == speech
    assert len(original) == len(result) + round(removed * rate)


def test_narration_segments_pack_original_sentences_without_rewriting():
    text = '第一句说明事实。第二句补充背景。\n' + '较长的背景，' * 18 + '最后收束。'
    segments = voice_synthesis.narration_segments(text)
    assert ''.join(segments) == text
    assert segments[0].startswith('第一句说明事实。第二句补充背景。')
    assert all(len(segment) <= 80 for segment in segments)


def test_tempo_shortens_audio_without_changing_pitch(tmp_path):
    import array
    import math

    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('FFmpeg is not available')
    sample = tmp_path / 'format.wav'
    _write(sample, .1)
    with wave.open(str(sample)) as stream:
        params = stream.getparams()
    rate = params.framerate
    original = array.array('h', (round(5000 * math.sin(2 * math.pi * 200 * i / rate))
                                 for i in range(rate * 3)))
    played = voice_synthesis._tempo(original, params, ffmpeg)
    assert len(played) / len(original) == pytest.approx(1 / 1.08, abs=.03)
    crossings = sum(a <= 0 < b for a, b in zip(played, played[1:], strict=False))
    assert crossings / (len(played) / rate) == pytest.approx(200, abs=2)


def test_qwen_checks_long_silence_after_gain_without_cutting_speech(tmp_path, monkeypatch):
    import array

    runtime = _qwen_runtime(tmp_path)
    runtime['voice_profile']['gain_db'] = -6

    def native(arguments, **kwargs):
        output = Path(arguments[arguments.index('--output') + 1])
        samples = array.array('h', [4000] * 1600 + [300] * 16000 + [4000] * 1600)
        with wave.open(str(output), 'wb') as stream:
            stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            stream.writeframes(samples.tobytes())
        output.with_suffix('.log').write_text('generated 2 frames', encoding='utf-8')

    monkeypatch.setattr(voice_synthesis, 'run_native', native)
    monkeypatch.setattr(voice_synthesis, '_tempo', lambda samples, params, ffmpeg: samples)
    voice = voice_synthesis.VoiceSynthesizer(runtime, tmp_path / 'cache')
    output = tmp_path / 'page.wav'
    result = voice.page('标题', '讲解。', output)
    assert result['silence_removed_seconds'] > 2
    with wave.open(str(output)) as stream:
        played = array.array('h', stream.readframes(stream.getnframes()))
    assert sum(value > 1800 for value in played) == 6400
