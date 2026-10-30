"""按完整意群生成本地配音，以内容缓存复用原始语音和逐页停顿。"""
from __future__ import annotations

import array
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import wave
from copy import deepcopy
from pathlib import Path

from .speech_text import spoken_numbers


class NativeInferenceError(RuntimeError):
    """处理：标记原生语音进程启动、推理或 GPU 层加载失败。
    输入：原生进程返回的错误或设备加载诊断。
    输出：允许同模型 CPU 重试的错误，本地文件读写错误单独报告。
    """


def narration_sentences(text: str) -> list[str]:
    """处理：按句末标点切分讲稿，保留英文缩写、小数和完整句子。
    输入：日报已写好的标题或短讲解，不重新撰写内容。
    输出：保留原标点的有序句子，逗号和单词内部不拆分。
    """
    sentences, start = [], 0
    for match in re.finditer(r'[。！？!?；;]+[”’"\']?|\.(?!\d)[”’"\']?(?=\s|$)', text):
        end = match.end()
        if match.group().startswith('.'):
            token = re.search(r'[\w.]+\.$', text[:end])
            word = token.group().lower() if token else ''
            if word in {'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'e.g.', 'i.e.', 'vs.', 'no.'}:
                continue
            if re.fullmatch(r'(?:[a-z]\.)+', word):
                continue
        sentence = text[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
    if text[start:].strip():
        sentences.append(text[start:].strip())
    return sentences



def narration_segments(text: str) -> list[str]:
    """处理：按原标点划分长句并合并相邻短句，减少模型重复加载。
    输入：页面摘要和讲解原文，段落换行保留。
    输出：不改变文字顺序的有序意群，单段尽量不超过 80 字符。
    """
    units = []
    cursor = 0
    for paragraph in text.splitlines(keepends=True):
        for sentence in narration_sentences(paragraph):
            chunks = (re.split(r'(?<=[，、；：,;:])', sentence)
                      if len(sentence) > 80 else [sentence])
            for chunk in chunks:
                if not chunk:
                    continue
                start = text.index(chunk, cursor)
                end = start + len(chunk)
                units.append(text[cursor:end])
                cursor = end
    if cursor < len(text):
        units.append(text[cursor:])
    packed = []
    for unit in units:
        if packed and len(packed[-1]) + len(unit) <= 80:
            packed[-1] += unit
        else:
            packed.append(unit)
    return [unit for unit in packed if unit.strip()]


def spoken_narration(text: str, language: str, pronunciations: dict) -> str:
    """处理：先应用音色配置的专名读法，再展开同值数字口语。
    输入：展示文字、输出语言和由写作宿主提供的专名别名。
    输出：仅供 TTS 使用的朗读副本，原始标题及短稿保持原样。
    """
    if pronunciations:
        names = sorted(pronunciations, key=len, reverse=True)
        pattern = r'(?<![A-Za-z0-9_])(?:' + '|'.join(map(re.escape, names)) + r')(?![A-Za-z0-9_])'
        aliases = {key.casefold(): value for key, value in pronunciations.items()}
        text = re.sub(pattern, lambda match: aliases[match.group().casefold()],
                      text, flags=re.IGNORECASE)
    return spoken_numbers(text, language)


def run_native(arguments: list[str], *, library_dir: Path | None = None) -> None:
    """处理：运行原生语音或编码程序，保存配音日志并报告实际错误。
    输入：不经过 shell 的参数列表；库目录随当前系统加入子进程环境。
    输出：成功返回，失败或 CUDA 回退 CPU 时给出日志中的原因。
    """
    directory = Path(arguments[0]).resolve().parent
    environment = os.environ.copy()
    variable = ('PATH' if sys.platform == 'win32' else
                'DYLD_LIBRARY_PATH' if sys.platform == 'darwin' else 'LD_LIBRARY_PATH')
    paths = [str(directory), str(directory.parent / 'lib')]
    if library_dir:
        paths += sorted({str(path.parent) for path in Path(library_dir).rglob('*')
                         if path.is_file()})
    environment[variable] = os.pathsep.join(paths + [environment.get(variable, '')])
    try:
        result = subprocess.run(arguments, capture_output=True, env=environment,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError as error:
        if '--mmproj-device' in arguments:
            raise NativeInferenceError(str(error)) from error
        raise
    diagnostic = (result.stdout + result.stderr).decode('utf-8', errors='replace')
    for argument in arguments:
        if argument.startswith('--output-filename='):
            Path(argument.split('=', 1)[1]).with_suffix('.log').write_text(
                diagnostic, encoding='utf-8')
    if '--output' in arguments:
        Path(arguments[arguments.index('--output') + 1]).with_suffix('.log').write_text(
            diagnostic, encoding='utf-8')
    if result.returncode:
        raise NativeInferenceError(diagnostic[-4000:])
    if re.search(r'OOV (?:word|character) skipped:|Skip unknown token:', diagnostic):
        raise ValueError('TTS skipped a name or word; add a pronunciation alias before retry. '
                         + diagnostic[-4000:])
    if '--provider=cuda' in arguments and 'fallback to cpu' in diagnostic.lower():
        raise RuntimeError('CUDA initialization fell back to CPU; choose CPU or a working CUDA '
                           'runtime. ' + diagnostic[-2000:])
    if '--mmproj-device' in arguments and not re.search(
            r'offloaded [1-9]\d*/\d+ layers to GPU', diagnostic):
        raise NativeInferenceError('GPU layer offload was not confirmed in the native TTS log')


def _wave_samples(path: Path) -> tuple[tuple, array.array]:
    """处理：读取原生程序输出的整段 PCM，供停顿拼接与峰值检查。
    输入：本地十六位 PCM WAV 文件。
    输出：音频格式及有符号样点，不改变采样率或声音内容。
    """
    with wave.open(str(path)) as source:
        if source.getsampwidth() != 2:
            raise ValueError(f'Expected PCM16 WAV: {path}')
        samples = array.array('h')
        samples.frombytes(source.readframes(source.getnframes()))
        if not samples or len(samples) != source.getnframes() * source.getnchannels():
            raise ValueError(f'Incomplete WAV: {path}')
        if sys.byteorder != 'little':
            samples.byteswap()
        return source.getparams(), samples



def _check_qwen_log(path: Path, limit: int) -> None:
    """处理：检查原生生成日志中的帧数与上限。
    输入：Qwen 日志路径及本次帧数上限。
    输出：未截断时正常返回，缺少计数或达到上限时报错。
    """
    if not path.is_file():
        raise ValueError(f'Missing Qwen synthesis log: {path}')
    frames = re.search(r'generated (\d+) frames', path.read_text(encoding='utf-8'))
    if not frames:
        raise ValueError(f'Missing Qwen frame count: {path}')
    if int(frames.group(1)) >= limit:
        raise ValueError('TTS reached the frame limit; split the original sentence at punctuation')


def _wave_digest(path: Path) -> str:
    """处理：检查 PCM 长度并计算文件摘要。
    输入：整页原始或播放 WAV 路径。
    输出：SHA-256 摘要，供判断音频能否重放。
    """
    with wave.open(str(path)) as source:
        expected = source.getnframes() * source.getnchannels() * source.getsampwidth()
        if source.getnframes() <= 0 or source.getsampwidth() != 2 or path.stat().st_size < expected:
            raise ValueError(f'Incomplete WAV: {path}')
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def _shorten_long_silences(samples: array.array, parameters: tuple) -> tuple[array.array, float]:
    """处理：缩短超长低能量空白，保留正常停顿和边界声音。
    输入：拼接后的 PCM 样点及其采样率、声道数。
    输出：缩短后的样点和删去的秒数，不修改原生缓存。
    """
    channels = parameters.nchannels
    rate = parameters.framerate
    window = max(1, rate // 50) * channels
    silent = []
    for start in range(0, len(samples), window):
        block = samples[start:start + window]
        silent.append(sum(value * value for value in block) < len(block) * 184**2)
    runs = []
    start = None
    for index, is_silent in enumerate([*silent, False]):
        if is_silent and start is None:
            start = index
        elif not is_silent and start is not None:
            end = min(index * window, len(samples))
            begin = start * window
            if end - begin > rate * channels and (begin or end < len(samples)):
                keep = round((.20 if begin == 0 or end == len(samples) else .70) * rate)
                keep *= channels
                left = (keep // (2 * channels)) * channels
                runs.append((begin + left, end - (keep - left)))
            start = None
    if not runs:
        return samples, 0.0
    result = array.array('h')
    cursor = 0
    fade = max(1, rate // 200)
    for begin, end in runs:
        result.extend(samples[cursor:begin])
        # 只在低能量切口的两侧渐变，避免波形跳变产生点击声。
        for frame in range(min(fade, len(result) // channels)):
            for channel in range(channels):
                pos = len(result) - (frame + 1) * channels + channel
                result[pos] = round(result[pos] * frame / fade)
        cursor = end
        boundary = min(fade * channels, len(samples) - cursor)
        for offset in range(0, boundary, channels):
            for channel in range(channels):
                result.append(round(samples[cursor + offset + channel] *
                                    (offset // channels) / fade))
        cursor += boundary
    result.extend(samples[cursor:])
    return result, (len(samples) - len(result)) / rate / channels


def _tempo(samples: array.array, parameters: tuple, ffmpeg: str | Path) -> array.array:
    """处理：按 1.08 倍语速调整播放音频，保持音高。
    输入：拼接后的 PCM 样点、音频格式及本地 FFmpeg 程序。
    输出：改变时长后的 PCM 样点，原始句段不变。
    """
    data = io.BytesIO()
    with wave.open(data, 'wb') as target:
        target.setparams(parameters)
        target.writeframes(samples.tobytes())
    result = subprocess.run([str(ffmpeg), '-v', 'error', '-i', 'pipe:0', '-filter:a',
                             'atempo=1.08', '-c:a', 'pcm_s16le', '-f', 'wav', 'pipe:1'],
                            input=data.getvalue(), capture_output=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
    with wave.open(io.BytesIO(result.stdout)) as source:
        values = array.array('h')
        values.frombytes(source.readframes(source.getnframes()))
    return values

def _write_wave(path: Path, parameters: tuple, samples: array.array) -> None:
    """处理：保存拼接或线性增益后的 PCM，不增加其他音效。
    输入：WAV 格式与十六位样点数组。
    输出：可直接量时和播放的本地 WAV。
    """
    values = array.array('h', samples)
    if sys.byteorder != 'little':
        values.byteswap()
    with wave.open(str(path), 'wb') as target:
        target.setparams(parameters)
        target.writeframes(values.tobytes())


class VoiceSynthesizer:
    """处理：将已写好的短稿转成可复用的语音与逐页音频。
    输入：原生运行工具、选中音色及可选参考材料。
    输出：可追溯的原始配音、显式停顿和本地缓存。
    """

    def __init__(self, runtime: dict, cache_root: Path, *, threads: int = 2):
        """处理：冻结本次音色、参考、模型和运行参数，建立共享句子缓存。
        输入：本地运行工具、可选音色配置和数据根中的缓存目录。
        输出：仅依赖选中声音与内容的缓存；画面及页面顺序不影响配音。
        """
        self.profile = runtime.get('voice_profile') or {}
        self.runtime = runtime
        self.cache_root = cache_root
        self.threads = threads
        self.fallback_reason = runtime.get('fallback_reason')
        self.engine = self.profile.get('engine', 'vits')
        self.provider = runtime['provider']
        self.model_dir = Path(runtime['model_dir'])
        self.executable = Path(runtime['tts_executable'])
        self.speed = self.profile.get('speed', 1)
        self.gain_db = self.profile.get('gain_db', 0)
        self.pauses = {'title': .45, 'sentence': .35, 'end': .2} | self.profile.get('pauses', {})
        base = [str(self.executable), f'--provider={self.provider}', f'--num-threads={threads}',
                '--tts-silence-scale=1', f'--speed={self.speed}']
        identity = {'version': 'voice-v1', 'engine': self.engine, 'provider': self.provider,
                    'threads': threads, 'speed': self.speed, 'gain_db': self.gain_db,
                    'pauses': self.pauses}
        files = [self.executable]
        self.reference = None
        if self.engine == 'qwen3':
            self.reference = next(entry for entry in self.profile['references']
                                  if entry['id'] == self.profile['reference_id'])
            model = Path(runtime['model_path'])
            projector = Path(runtime['mmproj_path'])
            files += [model, projector]
            identity.update(reference_hash=hashlib.sha256(
                Path(self.reference['audio']).read_bytes()).hexdigest(),
                seed=self.profile.get('seed', 42), context=self.profile.get('context', 4096),
                frames=self.profile.get('max_frames', 500))
            base = [str(self.executable), '-m', str(model), '-mm', str(projector),
                    '--tts-speaker-file', str(self.reference['audio']),
                    '-c', str(identity['context']), '--seed', str(identity['seed']),
                    '-t', str(threads), '-n', str(identity['frames']), '--verbosity', '5']
            if self.provider == 'cpu':
                base += ['--device', 'none', '-ngl', '0', '--no-mmproj-offload']
            else:
                device_name = runtime['device_name']
                base += ['--device', device_name, '--mmproj-device', device_name, '-ngl', '99']
        elif self.engine == 'zipvoice':
            self.reference = next(entry for entry in self.profile['references']
                                  if entry['id'] == self.profile['reference_id'])
            identity.update(reference_text=self.reference['text'],
                            reference_hash=hashlib.sha256(
                                Path(self.reference['audio']).read_bytes()).hexdigest(),
                            steps=self.profile.get('steps', 8),
                            target_rms=self.profile.get('target_rms', .05),
                            reference_gain_db=self.profile.get('reference_gain_db', -6))
            files += [self.model_dir / name for name in
                      ('encoder.onnx', 'decoder.onnx', 'vocos_24khz.onnx',
                       'tokens.txt', 'lexicon.txt')]
            base += [f'--zipvoice-{key}={self.model_dir / name}' for key, name in
                     [('encoder', 'encoder.onnx'), ('decoder', 'decoder.onnx'),
                      ('vocoder', 'vocos_24khz.onnx'), ('tokens', 'tokens.txt'),
                      ('lexicon', 'lexicon.txt')]]
            english = self.model_dir / 'lexicon-en-us-zipvoice.txt'
            if not english.is_file() and (self.model_dir / 'lexicon-en-us.txt').is_file():
                raise ValueError('Prepare the ZipVoice-compatible English lexicon before synthesis')
            if english.is_file():
                files.append(english)
                base[-1] += ',' + str(english)
            base += ['--debug=1', f'--num-steps={identity["steps"]}',
                     f'--zipvoice-target-rms={identity["target_rms"]}']
        else:
            model = (self.model_dir / 'model.onnx' if self.provider == 'cuda' else
                     next(iter(sorted(self.model_dir.glob('*int8.onnx'))), None))
            model = model or next(self.model_dir.glob('*.onnx'), None)
            if model is None:
                raise ValueError(f'TTS ONNX model missing: {self.model_dir}')
            files += [model, self.model_dir / 'tokens.txt', self.model_dir / 'lexicon.txt']
            base += [f'--vits-model={model}', f'--vits-tokens={files[-2]}',
                     f'--vits-lexicon={files[-1]}']
            rules = [self.model_dir / name for name in
                     ('date.fst', 'number.fst', 'phone.fst', 'new_heteronym.fst')
                     if (self.model_dir / name).is_file()]
            files += rules
            if rules:
                base.append('--tts-rule-fsts=' + ','.join(map(str, rules)))
        identity['files'] = [(str(path.resolve()), path.stat().st_size,
                              path.stat().st_mtime_ns) for path in files]
        synthesis_identity = {key: value for key, value in identity.items()
                              if key not in {'gain_db', 'pauses'}}
        digest = hashlib.sha256(
            json.dumps(synthesis_identity, sort_keys=True).encode()).hexdigest()[:20]
        self.cache = cache_root / digest
        self.cache.mkdir(parents=True, exist_ok=True)
        self.arguments = base
        self.identity = identity
        self.hits = self.generated = self.page_hits = 0
        if self.engine == 'zipvoice':
            prepared = self.cache / 'reference.wav'
            if not prepared.exists():
                run_native([str(runtime['ffmpeg']), '-y', '-i', str(self.reference['audio']),
                            '-af', f'volume={identity["reference_gain_db"]}dB',
                            '-ac', '1', '-c:a', 'pcm_s16le', str(prepared)])
            config = self.cache / 'reference.conf'
            # UTF-8 文件绕过 Windows CRT 对中文 reference-text 参数的 ANSI 转换。
            config.write_text('--reference-text=' + self.reference['text'] + '\n', encoding='utf-8')
            self.arguments += [f'--reference-audio={prepared}', f'--config={config}']

    def page(self, title: str, brief: str, destination: Path,
             *, language: str = "zh-CN") -> dict:
        """处理：GPU 执行失败时整页改用同模型 CPU 配音，并保留回退原因。
        输入：已写好的标题、短稿与目标语言。
        输出：实际设备一致的整页配音，已生成的音频可由对应设备缓存复用。
        """
        started = time.perf_counter()
        cache_identity = {'version': 'page-audio-v4-gain-aligned-tempo-1.08',
                          'normalization': 'spoken-numbers-v2',
                          'title': title, 'brief': brief, 'language': language,
                          'settings': self.identity, 'device': self.runtime.get('device_name'),
                          'peak_limit': self.profile.get('peak_limit', .98),
                          'pronunciations': self.profile.get('pronunciations', {}),
                          'reference_id': self.reference['id'] if self.reference else None}
        key = hashlib.sha256(json.dumps(cache_identity, sort_keys=True,
                                        ensure_ascii=False).encode()).hexdigest()
        manifest_path = destination.with_suffix('.voice.json')
        raw_page = destination.with_suffix('.raw.wav')
        if manifest_path.is_file() and destination.is_file() and raw_page.is_file():
            try:
                cached = json.loads(manifest_path.read_text(encoding='utf-8'))
                if (cached.get('page_cache_key') == key
                        and cached.get('audio_sha256') == _wave_digest(destination)
                        and cached.get('raw_sha256') == _wave_digest(raw_page)):
                    self.page_hits += 1
                    result = deepcopy(cached)
                    for segment in result['segments']:
                        segment['original_seconds'] = segment['seconds']
                        segment['seconds'] = 0.0
                    result.update(page_cache_hit=True, page_seconds=time.perf_counter() - started)
                    return result
            except (OSError, ValueError, EOFError, wave.Error, KeyError, json.JSONDecodeError):
                pass
        try:
            result = self._page(title, brief, destination, language=language)
        except NativeInferenceError as error:
            if self.engine != 'qwen3' or self.provider == 'cpu':
                raise
            from .video_runtime import cpu_video_runtime

            reason = str(error)
            generated, hits, page_hits = self.generated, self.hits, self.page_hits
            runtime = cpu_video_runtime(self.runtime)
            self.__init__(runtime, self.cache_root, threads=self.threads)
            self.fallback_reason = reason
            self.generated, self.hits, self.page_hits = generated, hits, page_hits
            return self.page(title, brief, destination, language=language)
        result.update(page_cache_key=key, audio_sha256=_wave_digest(destination),
                      raw_sha256=_wave_digest(raw_page))
        manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        result.update(page_cache_hit=False, page_seconds=time.perf_counter() - started)
        return result

    def _page(self, title: str, brief: str, destination: Path,
             *, language: str = "zh-CN") -> dict:
        """处理：Qwen 按页合成并复用旧句子缓存，其他引擎按句合成；检查时长与峰值。
        输入：日报标题、已写短讲解和本次导出 WAV 路径。
        输出：原始及播放 WAV、合成命令和实际时长。
        """
        if not brief.strip():
            raise ValueError('Missing slide summary and narration for video speech')
        parts = [title.strip()]
        if self.engine == 'qwen3':
            parts.extend(narration_segments(brief))
        else:
            parts.extend(narration_sentences(brief))
        segments, joined, parameters = [], array.array('h'), None
        for index, text in enumerate(parts):
            spoken = spoken_narration(text, language, self.profile.get('pronunciations', {}))
            key = hashlib.sha256((language + '\0' + spoken).encode()).hexdigest()[:24]
            raw = self.cache / f'{key}.wav'
            command = [*self.arguments, f'--output-filename={raw}', spoken]
            if self.engine == 'qwen3':
                text_file = raw.with_suffix('.txt')
                text_file.write_text(spoken, encoding='utf-8')
                command = [*self.arguments, '--tts-lang',
                           'en' if language.lower().startswith('en') else 'zh',
                           '-f', str(text_file), '--output', str(raw.with_suffix('.pending.wav'))]
            started = time.perf_counter()
            if raw.exists():
                try:
                    _wave_samples(raw)
                    if self.engine == 'qwen3':
                        _check_qwen_log(raw.with_suffix('.log'), self.identity['frames'])
                except (ValueError, EOFError, wave.Error):
                    raw.rename(raw.with_name(raw.stem + f'.invalid-{time.time_ns()}.wav'))
            if not raw.exists():
                if self.engine == 'qwen3':
                    run_native(command, library_dir=self.runtime.get('library_dir'))
                else:
                    run_native(command)
                if self.engine == 'qwen3':
                    pending = raw.with_suffix('.pending.wav')
                    _wave_samples(pending)
                    log = pending.with_suffix('.log')
                    _check_qwen_log(log, self.identity['frames'])
                    pending.replace(raw)
                    if log.exists():
                        log.replace(raw.with_suffix('.log'))
                self.generated += 1
            else:
                log = raw.with_suffix('.log')
                if (log.exists() and re.search(
                        r'OOV (?:word|character) skipped:|Skip unknown token:',
                        log.read_text(encoding='utf-8'))):
                    raise ValueError('Cached synthesis skipped words; add pronunciation aliases')
                if (self.engine != 'qwen3' and self.provider == 'cuda' and log.exists()
                        and 'fallback to cpu' in log.read_text(encoding='utf-8').lower()):
                    raise RuntimeError('Cached CUDA synthesis fell back to CPU')
                self.hits += 1
            current, samples = _wave_samples(raw)
            if parameters is not None and current[:3] != parameters[:3]:
                raise ValueError('Voice segments have different audio formats')
            parameters = current
            pause = (self.pauses['end'] if index == len(parts) - 1 else
                     self.pauses['title'] if index == 0 else self.pauses['sentence'])
            joined.extend(samples)
            joined.extend([0] * round(pause * parameters.framerate) * parameters.nchannels)
            segments.append({'text': text, 'display_text': text, 'spoken_text': spoken,
                             'language': language, 'raw_path': str(raw), 'pause': pause,
                             'duration': current.nframes / current.framerate,
                             'seconds': time.perf_counter() - started, 'command': command})
        raw_joined = joined
        raw_page = destination.with_suffix('.raw.wav')
        _write_wave(raw_page, parameters, raw_joined)
        peak = max(abs(value) for value in joined)
        full_scale_samples = sum(abs(value) >= 32767 for value in joined)
        peak_limit = self.profile.get('peak_limit', .98)
        gain = min(10 ** (self.gain_db / 20), peak_limit * 32767 / max(1, peak))
        played = array.array('h', (round(value * gain) for value in joined))
        shortened = 0.0
        if self.engine == 'qwen3':
            played, shortened = _shorten_long_silences(played, parameters)
        played = _tempo(played, parameters, self.runtime['ffmpeg'])
        duration = len(played) / parameters.framerate / parameters.nchannels
        _write_wave(destination, parameters, played)
        manifest = {'voice': self.profile.get('name'), 'engine': self.engine,
                    'provider': self.provider, 'fallback_reason': self.fallback_reason,
                    'language': language, 'display_text': title + '\n' + brief,
                    'spoken_text': '\n'.join(segment['spoken_text'] for segment in segments),
                    'reference_id': self.reference['id'] if self.reference else None,
                    'settings': self.identity, 'segments': segments, 'duration': duration,
                    'silence_removed_seconds': shortened, 'tempo': 1.08,
                    'raw_path': str(raw_page), 'audio_path': str(destination),
                    'gain_db': 20 * math.log10(gain), 'raw_peak': peak / 32768,
                    'full_scale_samples': full_scale_samples, 'sample_count': len(joined),
                    'full_scale_fraction': full_scale_samples / len(joined)}
        return manifest
