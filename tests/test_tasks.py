import json
import wave

import pytest

from qab.clips import prepare_clips
from qab.schema import Case, SubmissionMeta
from qab.tasks import (SegmentationSubmission, TimingSubmission, evaluate_task,
                       maximum_matches, reviewed_clips)


@pytest.fixture
def case():
    return Case(id='sample', duration_s=12, style='hadr', content='prayer', noisy=False, multi_surah=False,
                words=[{'word': '2:1:1', 'start_s': 2, 'end_s': 3},
                       {'word': '2:2:1', 'start_s': 3, 'end_s': 4},
                       {'word': '2:2:2', 'start_s': 6, 'end_s': 8}],
                segments=[{'first_word': '2:1:1', 'last_word': '2:2:1', 'start_s': 2, 'end_s': 4},
                          {'first_word': '2:2:2', 'last_word': '2:2:2', 'start_s': 6, 'end_s': 8}],
                non_quran=[{'start_s': 9, 'end_s': 11}])


def seg(case, intervals):
    return SegmentationSubmission(case_id=case.id, segments=[{'start_s': a, 'end_s': b} for a, b in intervals])


def timing(case):
    return TimingSubmission(case_id=case.id, clips=[{'words': [
        {'start_s': w.start_s - s.start_s, 'end_s': w.end_s - s.start_s} for w in ws]}
        for s, ws in reviewed_clips(case)])


def test_perfect_empty_and_non_quran_ignored(case):
    perfect = evaluate_task('segmentation', [case], [seg(case, [(2, 4), (6, 8), (9, 11)])])
    assert perfect['pooled']['segments_f1'] == perfect['pooled']['boundaries_f1'] == 1
    empty = evaluate_task('segmentation', [case], [seg(case, [])])
    assert empty['pooled']['segments_f1'] == 0
    assert empty['pooled']['segments_correct'] is None


@pytest.mark.parametrize('interval,accepted', [((2.75, 4), True), ((2.751, 4), False),
                                             ((2, 3.25), True), ((2, 3.249), False),
                                             ((0, 4), True), ((2, 5.99), True)])
def test_segmentation_tolerances(case, interval, accepted):
    result = evaluate_task('segmentation', [case], [seg(case, [interval])])
    assert result['counts']['segments_matched'] == int(accepted)


def test_neighbor_and_non_quran_limits(case):
    result = evaluate_task('segmentation', [case], [seg(case, [(6, 9.75)])])
    assert result['counts']['segments_matched'] == 1
    result = evaluate_task('segmentation', [case], [seg(case, [(6, 9.751)])])
    assert result['counts']['segments_matched'] == 0


def test_split_merge_and_short_fragment(case):
    for intervals in [[(2, 8)], [(2, 3), (3, 4), (6, 8)], [(2.75, 3.25), (6, 8)]]:
        result = evaluate_task('segmentation', [case], [seg(case, intervals)])
        assert result['pooled']['segments_f1'] < 1


def test_maximum_matching_not_greedy():
    assert maximum_matches([[0, 1], [0]]) == 2
    assert maximum_matches([[0], [0], [0]]) == 1


def test_timing_perfect_null_and_shortcut(case):
    result = evaluate_task('timing', [case], [timing(case)])
    assert result['pooled'] == {'words_timed': 1, 'clean_clips': 1}
    a, b = timing(case), timing(case)
    a.clips[0].words = None
    b.clips[0].words = [None, None]
    ra = evaluate_task('timing', [case], [a])
    assert ra == evaluate_task('timing', [case], [b])
    assert ra['pooled']['words_timed'] == 1 / 3
    assert ra['pooled']['clean_clips'] == .5
    assert ra['diagnostics']['mean_boundary_error_ms'] is None


@pytest.mark.parametrize('error,passed', [(.299, True), (.3, True), (.301, False)])
def test_word_tolerance_both_edges(case, error, passed):
    pred = timing(case)
    pred.clips[0].words[0].end_s += error
    result = evaluate_task('timing', [case], [pred])
    assert result['counts']['words_at_0.3'] == 2 + passed
    assert result['counts']['clips_at_0.3'] == 1 + passed


def test_counts_and_clip_relative_validation(case):
    pred = timing(case)
    pred.clips.pop()
    with pytest.raises(ValueError, match='Expected 2 clips'):
        evaluate_task('timing', [case], [pred])
    pred = timing(case)
    pred.clips[0].words.pop()
    with pytest.raises(ValueError, match='Clip 1: expected 2'):
        evaluate_task('timing', [case], [pred])
    pred = timing(case)
    pred.clips[1].words[0].end_s = 8
    with pytest.raises(ValueError, match='relative to the clip start'):
        evaluate_task('timing', [case], [pred])


def test_pooled_weighting(case):
    other = case.model_copy(deep=True)
    other.id = 'other'
    other.segments = other.segments[1:]
    other.words = other.words[2:]
    failed = TimingSubmission(case_id='other', clips=[{'words': None}])
    report = evaluate_task('timing', [case, other], [timing(case), failed])
    assert report['pooled']['words_timed'] == .75
    assert report['pooled']['clean_clips'] == 2 / 3


def test_runtime_only_segmentation(case):
    with pytest.raises(ValueError):
        TimingSubmission(case_id=case.id, clips=[], runtime_seconds=1)
    sub = seg(case, [(2, 4), (6, 8)])
    sub.runtime_seconds = 3
    meta = SubmissionMeta(system='Example', version='1', hardware_class='cpu', hardware='Test CPU')
    assert evaluate_task('segmentation', [case], [sub], meta)['pooled']['rtf'] == .25


def test_missing_segments_not_inferred(case):
    case.segments = []
    with pytest.raises(ValueError, match='Reviewed segments are missing'):
        reviewed_clips(case)


def test_clip_slicing_exact_samples(case, tmp_path):
    import shutil
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg is required for the audio utility integration test')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'sample.json').write_text(case.model_dump_json())
    with wave.open(str(source / 'sample.wav'), 'wb') as wav:
        wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 12 * 8000)
    output = prepare_clips(source, tmp_path / 'clips')
    info = json.loads((output / 'sample.json').read_text())
    assert info['clips'][0]['words'] == ['2:1:1', '2:2:1']
    assert 'start_s' not in json.dumps(info)
    for clip in info['clips']:
        with wave.open(str(output / clip['audio'])) as wav:
            assert wav.getnframes() == 16000


def test_existing_reference_endpoint_overrun(case):
    case.duration_s = 7.964
    result = evaluate_task('segmentation', [case], [seg(case, [(2, 4), (6, 8)])])
    assert result['pooled']['segments_f1'] == 1


def test_timing_schema_errors_identify_clip_and_word():
    from leaderboard.app import errors
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as exc:
        TimingSubmission(case_id='example', clips=[{'words': [{'start_s': -1, 'end_s': 1}]}])
    assert 'Clip 1, word 1, start_s:' in errors(exc.value)
