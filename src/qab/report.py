"""Aggregation and the report document: pooled headline, equal-case means, facet slices, diagnostics.

Implements docs/SPEC.md section 5. Pooled numbers sum the underlying counts
across cases before taking a ratio; nothing on the leaderboard is a mean of
per-case values.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from typing import Any

from . import __version__
from .scoring import CaseScore, FormulaCounts, f1, score_case
from .schema import Case, Submission, SubmissionMeta

ECE_BINS = 10


@dataclass
class Pooled:
    cases: int
    words_found: float | None
    words_correct: float | None
    words_f1: float | None
    clean_segments: float | None
    repeats_caught: float | None
    repeats_real: float | None
    repeats_f1: float | None
    words_per_segment: float | None
    rtf: float | None
    confidence_skill: float | None
    counts: dict[str, int]


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _confidence(pairs: list[tuple[float, int]]) -> dict[str, Any]:
    if not pairs:
        return {"reported": False, "skill": None, "state": "not_reported"}
    n = len(pairs)
    brier = sum((c - y) ** 2 for c, y in pairs) / n
    p = sum(y for _, y in pairs) / n
    flat = p * (1 - p)
    if flat > 0:
        skill, state = 1 - brier / flat, "skill"
    else:
        skill, state = 1 - brier, "degenerate"
    correct = sorted(c for c, y in pairs if y)
    wrong = sorted(c for c, y in pairs if not y)
    auroc = None
    if correct and wrong:
        better = sum(bisect.bisect_left(wrong, c) + 0.5 * (bisect.bisect_right(wrong, c) - bisect.bisect_left(wrong, c))
                     for c in correct)
        auroc = better / (len(correct) * len(wrong))
    bins = [[0, 0.0, 0.0] for _ in range(ECE_BINS)]
    for c, y in pairs:
        b = min(int(c * ECE_BINS), ECE_BINS - 1)
        bins[b][0] += 1
        bins[b][1] += c
        bins[b][2] += y
    ece = sum(cnt / n * abs(sc / cnt - sy / cnt) for cnt, sc, sy in bins if cnt)
    return {"reported": True, "skill": skill, "state": state, "brier": brier, "brier_flat": flat,
            "auroc": auroc, "ece": ece, "words": n,
            "min_confidence_correct": correct[0] if correct else None,
            "max_confidence_wrong": wrong[-1] if wrong else None}


def pool(scores: list[CaseScore], runtime_reported: bool) -> Pooled:
    c = {
        "quran_instances": sum(s.quran_instances for s in scores),
        "matched_words": sum(s.matched_words for s in scores),
        "claimed_words": sum(s.claimed_words for s in scores),
        "quran_segments": sum(s.quran_segments for s in scores),
        "clean_segments": sum(s.clean_segments for s in scores),
        "truth_repeats": sum(s.truth_repeats for s in scores),
        "predicted_repeats": sum(s.predicted_repeats for s in scores),
        "caught_repeats": sum(s.caught_repeats for s in scores),
        "denied": sum(s.denied for s in scores),
        "uncovered": sum(s.uncovered for s in scores),
        "false_over_non_quran": sum(s.false_over_non_quran for s in scores),
        "instances_in_clean": sum(s.instances_in_clean for s in scores),
    }
    found, correct = _ratio(c["matched_words"], c["quran_instances"]), _ratio(c["matched_words"], c["claimed_words"])
    caught, real = _ratio(c["caught_repeats"], c["truth_repeats"]), _ratio(c["caught_repeats"], c["predicted_repeats"])
    rtf = None
    if runtime_reported:
        rtf = sum(s.runtime_seconds for s in scores) / sum(s.duration_s for s in scores)
    conf = _confidence([p for s in scores for p in s.confidence_pairs])
    return Pooled(
        cases=len(scores), words_found=found, words_correct=correct, words_f1=f1(correct, found),
        clean_segments=_ratio(c["clean_segments"], c["quran_segments"]),
        repeats_caught=caught, repeats_real=real, repeats_f1=f1(real, caught),
        words_per_segment=_ratio(c["claimed_words"], c["quran_segments"]), rtf=rtf,
        confidence_skill=conf["skill"], counts=c)


def equal_case(scores: list[CaseScore]) -> dict[str, float | None]:
    per = [pool([s], s.runtime_seconds is not None) for s in scores]
    keys = ["words_found", "words_correct", "words_f1", "clean_segments", "repeats_caught", "repeats_real",
            "repeats_f1", "words_per_segment", "rtf"]
    return {k: _mean([getattr(p, k) for p in per]) for k in keys}


def _formulas(scores: list[CaseScore]) -> dict[str, dict[str, int]]:
    out: dict[str, FormulaCounts] = {}
    for s in scores:
        for kind, fc in s.formulas.items():
            agg = out.setdefault(kind, FormulaCounts())
            agg.occurrences += fc.occurrences
            agg.detected += fc.detected
            agg.exact += fc.exact
            agg.extra += fc.extra
    return {kind: {**asdict(fc), "missed": fc.missed} for kind, fc in out.items()}


def _headline(p: Pooled, hardware_class: str | None) -> dict[str, Any]:
    return {"words_f1": p.words_f1, "clean_segments": p.clean_segments, "repeats_f1": p.repeats_f1,
            "words_per_segment": p.words_per_segment, "rtf": p.rtf, "hardware_class": hardware_class,
            "confidence_skill": p.confidence_skill}


def corpus_fingerprint(cases: list[Case]) -> str:
    """sha256 over the scored content of the corpus (ids, durations, words, non_quran), so a report
    proves which truth it was computed against whatever `corpus_version` label it carries."""
    h = hashlib.sha256()
    for case in sorted(cases, key=lambda c: c.id):
        h.update(json.dumps({"id": case.id, "duration_s": case.duration_s, "riwayah": case.riwayah,
                             "words": [[w.word, w.start_s, w.end_s] for w in case.words],
                             "non_quran": [[iv.start_s, iv.end_s] for iv in case.non_quran]},
                            separators=(",", ":")).encode())
    return h.hexdigest()


def _diagnostics(scores: list[CaseScore], counts: dict[str, int]) -> dict[str, Any]:
    errors = [e for s in scores for e in s.repeat_position_errors]
    return {k: counts[k] for k in ("denied", "uncovered", "false_over_non_quran", "instances_in_clean")} | {
        "word_weighted_clean": _ratio(counts["instances_in_clean"], counts["quran_instances"]),
        "repeat_position_error_median_words": statistics.median(errors) if errors else None,
    }


def evaluate(cases: list[Case], submissions: list[Submission], meta: SubmissionMeta | None = None,
             corpus_version: str | None = None) -> dict[str, Any]:
    """Score one submission set against a corpus and return the report document.

    Every case must have exactly one submission; a missing or duplicated
    case is an error, because a partial submission would be incomparable.
    Runtime and confidence are all-or-nothing across the cases: reported for
    a strict subset means not reported.
    """
    if not cases:
        raise ValueError("empty corpus")
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids in the corpus")
    by_case: dict[str, Submission] = {}
    for sub in submissions:
        if sub.case_id in by_case:
            raise ValueError(f"duplicate submission for case {sub.case_id!r}")
        by_case[sub.case_id] = sub
    missing = [c.id for c in cases if c.id not in by_case]
    unknown = sorted(set(by_case) - set(ids))
    if missing or unknown:
        raise ValueError(f"submission set does not match the corpus: missing {missing}, unknown {unknown}")
    runtime_reported = all(by_case[c.id].runtime_seconds is not None for c in cases)
    if runtime_reported and (meta is None or meta.hardware_class is None):
        raise ValueError("runtime_seconds is reported but submission.json carries no hardware_class")
    confidence_reported = all(by_case[c.id].confidence_reported for c in cases)
    scores = []
    for case in cases:
        s = score_case(case, by_case[case.id])
        if not runtime_reported:
            s.runtime_seconds = None
        if not confidence_reported:
            s.confidence_pairs = []
        scores.append(s)
    hardware_class = meta.hardware_class if (meta and runtime_reported) else None
    overall = pool(scores, runtime_reported)
    facet_names = sorted({k for s in scores for k in s.facets})
    slices = {}
    for name in facet_names:
        for value in sorted({s.facets[name] for s in scores}):
            subset = [s for s in scores if s.facets[name] == value]
            slices[f"{name}={value}"] = {"cases": [s.case_id for s in subset],
                                        "pooled": asdict(pool(subset, runtime_reported)),
                                        "equal_case": equal_case(subset)}
    return {
        "scorer_version": __version__,
        "corpus_version": corpus_version,
        "corpus_fingerprint": corpus_fingerprint(cases),
        "submission": meta.model_dump() if meta else None,
        "runtime_reported": runtime_reported,
        "confidence_reported": confidence_reported,
        "headline": _headline(overall, hardware_class),
        "pooled": asdict(overall),
        "equal_case": equal_case(scores),
        "slices": slices,
        "formulas": _formulas(scores),
        "confidence": _confidence([p for s in scores for p in s.confidence_pairs]),
        "diagnostics": _diagnostics(scores, overall.counts),
        "cases": [_case_document(s) for s in scores],
    }


def _case_document(s: CaseScore) -> dict[str, Any]:
    p = pool([s], s.runtime_seconds is not None)
    return {
        "case_id": s.case_id, "duration_s": s.duration_s, "facets": s.facets,
        "pooled": asdict(p),
        "formulas": {k: {**asdict(v), "missed": v.missed} for k, v in s.formulas.items()},
        "diagnostics": _diagnostics([s], p.counts),
        "segments": [asdict(seg) for seg in s.segments],
    }