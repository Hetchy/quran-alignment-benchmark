"""Independent segmentation and supplied-reference timing scorers. No audio inference."""
from __future__ import annotations

import hashlib
import json
from bisect import bisect_left, bisect_right
from collections import Counter

from pydantic import Field, model_validator

from .report import corpus_fingerprint
from .schema import Interval, Strict

TASK_VERSION = '1'
SEG_EPS = .75
SEG_PAD = 2.0
WORD_TOL = .3
TOLERANCES = (.05, .1, .2, .3, .5)


class SegmentationSubmission(Strict):
    case_id: str
    segments: list[Interval] = Field(max_length=100000)
    runtime_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def ordered(self):
        for i, (a, b) in enumerate(zip(self.segments, self.segments[1:]), 1):
            if b.start_s < a.end_s - 1e-9:
                raise ValueError(f'Segments {i} and {i + 1} overlap or are out of order. '
                                 'Provide ordered, non-overlapping speech intervals.')
        return self


class ClipPrediction(Strict):
    words: list[Interval | None] | None


class TimingSubmission(Strict):
    case_id: str
    clips: list[ClipPrediction]


MODELS = {'segmentation': SegmentationSubmission, 'timing': TimingSubmission}
PRIMARY = {'alignment': 'words_f1', 'segmentation': 'segments_f1', 'timing': 'words_timed'}


def reviewed_clips(case):
    """Use explicit dataset segments, never reconstruct waqf from gaps."""
    if not case.segments:
        raise ValueError('Reviewed segments are missing. Fetch the current pinned dataset again.')
    result, cursor = [], 0
    for i, seg in enumerate(case.segments, 1):
        words = []
        while cursor < len(case.words) and case.words[cursor].midpoint < seg.end_s:
            w = case.words[cursor]
            if w.start_s < seg.start_s - 1e-6 or w.end_s > seg.end_s + 1e-6:
                raise ValueError(f'Reference segment {i} does not contain its word times')
            words.append(w)
            cursor += 1
        if not words or words[0].word != seg.first_word or words[-1].word != seg.last_word:
            raise ValueError(f'Reference segment {i} does not match its word range')
        if i > 1 and seg.start_s < case.segments[i - 2].end_s - 1e-6:
            raise ValueError('Reference segments overlap or are out of order')
        result.append((seg, words))
    if cursor != len(case.words):
        raise ValueError('Reference segments do not cover all word occurrences')
    return result


def overlap(a, b):
    return max(0., min(a.end_s, b.end_s) - max(a.start_s, b.start_s))


def maximum_matches(edges):
    """Maximum cardinality one-to-one matching; iteration avoids recursion limits."""
    matched = {}
    for root in range(len(edges)):
        stack, seen, parent = [root], set(), {}
        terminal = None
        while stack and terminal is None:
            left = stack.pop()
            for right in edges[left]:
                if right in seen:
                    continue
                seen.add(right)
                parent[right] = left
                if right not in matched:
                    terminal = right
                    break
                stack.append(matched[right])
        if terminal is not None:
            reverse = {left: right for right, left in matched.items()}
            while terminal is not None:
                left = parent[terminal]
                previous = reverse.get(left)
                matched[terminal] = left
                terminal = previous
    return len(matched)


def segmentation_counts(case, sub):
    clips = reviewed_clips(case)
    targets = [(s, ws) for s, ws in clips if any(w.token[0] == 'q' for w in ws)]
    duration = max(case.duration_s, case.segments[-1].end_s)
    if any(s.end_s > duration + 1e-6 for s in sub.segments):
        raise ValueError('A segment exceeds the recording duration. Use recording-relative seconds.')
    ignored = list(case.non_quran) + [s for s, ws in clips if not any(w.token[0] == 'q' for w in ws)]
    windows = []
    for s, ws in targets:
        before = [w.end_s for w in case.words if w.end_s <= s.start_s + 1e-6]
        after = [w.start_s for w in case.words if w.start_s >= s.end_s - 1e-6]
        before += [iv.end_s for iv in case.non_quran if iv.end_s <= s.start_s]
        after += [iv.start_s for iv in case.non_quran if iv.start_s >= s.end_s]
        low = max(0, s.start_s - SEG_PAD, max(before) - SEG_EPS if before else 0)
        high = min(duration, s.end_s + SEG_PAD,
                   min(after) + SEG_EPS if after else duration)
        windows.append((low, s.start_s + SEG_EPS, s.end_s - SEG_EPS, high))
    relevant = []
    for p in sub.segments:
        touches_quran = any(overlap(p, s) > 1e-9 for s, _ in targets)
        if touches_quran or (not any(overlap(p, iv) > 1e-9 for iv in ignored)
                             and any(p.end_s > lo and p.start_s < hi for lo, _, _, hi in windows)):
            relevant.append(p)
    starts = [p.start_s for p in relevant]
    ends_sorted = sorted((p.end_s, i) for i, p in enumerate(relevant))
    ends = [e for e, _ in ends_sorted]
    segment_edges, start_edges, end_edges = [], [], []
    for (s, _), (lo, start_hi, end_lo, hi) in zip(targets, windows):
        start_ids = list(range(bisect_left(starts, lo - 1e-9), bisect_right(starts, start_hi + 1e-9)))
        end_ids = [i for _, i in ends_sorted[bisect_left(ends, end_lo - 1e-9):bisect_right(ends, hi + 1e-9)]]
        start_edges.append(start_ids)
        end_edges.append(end_ids)
        segment_edges.append([i for i in start_ids if i in end_ids
                              and relevant[i].end_s - relevant[i].start_s >= (s.end_s - s.start_s) / 2 - 1e-9
                              and sum(overlap(relevant[i], iv) for iv in ignored) <= SEG_EPS + 1e-9])
    return {'segments_matched': maximum_matches(segment_edges), 'segments_true': len(targets),
            'segments_predicted': len(relevant),
            'boundaries_matched': maximum_matches(start_edges) + maximum_matches(end_edges),
            'boundaries_true': 2 * len(targets), 'boundaries_predicted': 2 * len(relevant)}


def timing_counts(case, sub):
    clips = reviewed_clips(case)
    if len(sub.clips) != len(clips):
        raise ValueError(f'Expected {len(clips)} clips in dataset segment order; received {len(sub.clips)}. '
                         'Use {"words": null} for a clip that could not be timed.')
    counts = Counter(words_total=0, clips_total=len(clips), boundary_count=0, boundary_error_sum=0.)
    for i, ((seg, truth), prediction) in enumerate(zip(clips, sub.clips), 1):
        words = prediction.words if prediction.words is not None else [None] * len(truth)
        if len(words) != len(truth):
            raise ValueError(f'Clip {i}: expected {len(truth)} word entries, received {len(words)}. '
                             'Keep supplied word order; use null for an untimed word or words: null for the clip.')
        previous_start = -1.
        passing = Counter()
        for j, (w, pred) in enumerate(zip(truth, words), 1):
            counts['words_total'] += 1
            if pred is None:
                continue
            if pred.end_s > seg.end_s - seg.start_s + 1e-6 or pred.start_s < previous_start:
                raise ValueError(f'Clip {i}, word {j}: use ordered timestamps within the clip duration '
                                 f'({seg.end_s - seg.start_s:g} s), relative to the clip start.')
            previous_start = pred.start_s
            a = abs(pred.start_s - (w.start_s - seg.start_s))
            b = abs(pred.end_s - (w.end_s - seg.start_s))
            counts['boundary_error_sum'] += a + b
            counts['boundary_count'] += 2
            for tolerance in TOLERANCES:
                if max(a, b) <= tolerance + 1e-9:
                    passing[str(tolerance)] += 1
        for tolerance in TOLERANCES:
            key = str(tolerance)
            counts['words_at_' + key] += passing[key]
            counts['clips_at_' + key] += int(passing[key] == len(truth))
    return dict(counts)


def ratio(a, b):
    return a / b if b else None


def pooled(task, counts):
    if task == 'timing':
        return {'words_timed': ratio(counts.get('words_at_0.3', 0), counts['words_total']),
                'clean_clips': ratio(counts.get('clips_at_0.3', 0), counts['clips_total'])}
    result = {}
    for kind in ('segments', 'boundaries'):
        m, t, p = (counts[kind + '_' + k] for k in ('matched', 'true', 'predicted'))
        result.update({kind + '_f1': ratio(2 * m, t + p), kind + '_found': ratio(m, t),
                       kind + '_correct': ratio(m, p)})
    return result


def fingerprint(cases):
    body = {'alignment': corpus_fingerprint(cases),
            'segments': {c.id: [s.model_dump() for s in c.segments] for c in sorted(cases, key=lambda c: c.id)}}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def evaluate_task(task, cases, submissions, meta=None, corpus_version='v1'):
    by_id = {s.case_id: s for s in submissions}
    if len(by_id) != len(submissions) or set(by_id) != {c.id for c in cases}:
        raise ValueError('Provide exactly one prediction file for each selected recording ID.')
    total, records = Counter(), []
    for case in cases:
        counts = (timing_counts if task == 'timing' else segmentation_counts)(case, by_id[case.id])
        total.update(counts)
        records.append({'id': case.id, 'counts': counts, 'scores': pooled(task, counts)})
    scores = pooled(task, total)
    if task == 'segmentation':
        runtimes = [s.runtime_seconds for s in submissions]
        if any(r is not None for r in runtimes):
            if not all(r is not None for r in runtimes):
                raise ValueError('Runtime must be provided for every recording or none.')
            if not meta or not meta.hardware_class or not meta.hardware:
                raise ValueError('Runtime requires CPU/GPU and a hardware description.')
        scores['rtf'] = sum(runtimes) / sum(c.duration_s for c in cases) if runtimes and all(
            r is not None for r in runtimes) else None
    diagnostics = {}
    if task == 'timing':
        diagnostics['tolerances'] = {str(t): {
            'words_timed': ratio(total['words_at_' + str(t)], total['words_total']),
            'clean_clips': ratio(total['clips_at_' + str(t)], total['clips_total'])} for t in TOLERANCES}
        diagnostics['mean_boundary_error_ms'] = (1000 * ratio(total['boundary_error_sum'], total['boundary_count'])
                                                if total['boundary_count'] == 2 * total['words_total']
                                                and total['boundary_count'] else None)
    return {'task': task, 'task_scorer_version': TASK_VERSION, 'corpus_version': corpus_version,
            'corpus_fingerprint': fingerprint(cases), 'pooled': scores, 'headline': scores,
            'counts': dict(total), 'recordings': records, 'diagnostics': diagnostics}
