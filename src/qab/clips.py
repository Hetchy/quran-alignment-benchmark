"""Prepare exact reviewed clips from an offline `qab fetch` directory."""
import json
import subprocess
import tempfile
import wave
from pathlib import Path

from .corpus import load_cases
from .tasks import fingerprint, reviewed_clips


def prepare_clips(cases_dir, out_dir):
    cases = load_cases(cases_dir=cases_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for case in cases:
        clips = reviewed_clips(case)
        source = next((Path(cases_dir) / (case.id + ext) for ext in ('.mp3', '.wav', '.flac')
                       if (Path(cases_dir) / (case.id + ext)).exists()), None)
        if source is None:
            raise ValueError(f'{case.id}: audio missing. Run qab fetch first.')
        directory = out / case.id
        directory.mkdir(exist_ok=True)
        inputs = []
        # Decode once; preserve the source rate and channels. Round cuts to nearest sample.
        with tempfile.TemporaryDirectory() as temp:
            decoded = Path(temp) / 'decoded.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-c:a', 'pcm_s16le', str(decoded)],
                           check=True, capture_output=True)
            with wave.open(str(decoded), 'rb') as audio:
                for i, (segment, words) in enumerate(clips, 1):
                    start = round(segment.start_s * audio.getframerate())
                    end = round(segment.end_s * audio.getframerate())
                    if end > audio.getnframes() + audio.getframerate():
                        raise ValueError(f'{case.id}: segment {i} extends past decoded audio')
                    end = min(end, audio.getnframes())
                    audio.setpos(start)
                    name = f'{i:04d}.wav'
                    with wave.open(str(directory / name), 'wb') as clip:
                        clip.setparams(audio.getparams())
                        clip.writeframes(audio.readframes(end - start))
                    first = segment.first_word
                    reference = (f'{first}-{segment.last_word}' if words[0].token[0] == 'q'
                                 else first.split(':')[0])
                    inputs.append({'audio': f'{case.id}/{name}', 'reference': reference,
                                   'words': [w.word for w in words]})
        (out / f'{case.id}.json').write_text(json.dumps({'clips': inputs}, indent=2), encoding='utf-8')
    (out / 'manifest.json').write_text(json.dumps({'task': 'timing', 'corpus_fingerprint': fingerprint(cases),
                                                  'recordings': [c.id for c in cases]}, indent=2), encoding='utf-8')
    return out
