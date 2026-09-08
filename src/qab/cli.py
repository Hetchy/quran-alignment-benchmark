"""Command line: `qab validate`, `qab score`, `qab fetch`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .corpus import fetch, load_cases, load_submissions
from .report import evaluate
from .schema import Submission, SubmissionMeta
from .tasks import MODELS, evaluate_task
from .clips import prepare_clips


def _validate(directory: Path, task='alignment') -> int:
    """File-level validation: every file parses under its schema. Returns the error count."""
    if not directory.is_dir():
        print(f"{directory}: not a directory", file=sys.stderr)
        return 1
    files = sorted(directory.glob("*.json"))
    cases = [f for f in files if f.name != "submission.json"]
    if not cases:
        print(f"{directory}: no submission files (<case_id>.json)", file=sys.stderr)
        return 1
    errors, ids = 0, {}
    for f in files:
        try:
            if f.name == "submission.json":
                SubmissionMeta.model_validate_json(f.read_text(encoding="utf-8"))
            else:
                payload = json.loads(f.read_text(encoding="utf-8"))
                payload.setdefault("case_id", f.stem)
                sub = (Submission if task == "alignment" else MODELS[task]).model_validate(payload)
                if sub.case_id != f.stem:
                    raise ValueError("case_id must match the filename")
                if sub.case_id in ids:
                    raise ValueError(f"case_id {sub.case_id!r} already used by {ids[sub.case_id]}")
                ids[sub.case_id] = f.name
        except (ValidationError, ValueError) as exc:
            errors += 1
            print(f"{f.name}: {exc}", file=sys.stderr)
    if not (directory / "submission.json").exists():
        print("note: no submission.json (optional locally; runtime needs hardware metadata)")
    print(f"{directory}: {len(cases)} submission file(s), {errors} with errors")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qab", description="Quran alignment benchmark scorer")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="validate a directory of submission files")
    v.add_argument("directory", type=Path)

    s = sub.add_parser("score", help="score a directory of submission files against the corpus")
    s.add_argument("directory", type=Path)
    s.add_argument("--corpus", default="v1", help="corpus version (dataset config), default v1")
    s.add_argument("--cases", type=Path, default=None,
                   help="directory of case JSON files (from `qab fetch`) instead of the Hub")
    s.add_argument("--revision", default=None, help="dataset commit to pin when loading from the Hub")
    s.add_argument("--out", type=Path, default=None, help="write the report JSON here instead of stdout")
    s.add_argument("--summary", action="store_true", help="print the headline only")

    f = sub.add_parser("fetch", help="download audio and cases for offline runs")
    f.add_argument("--corpus", default="v1")
    f.add_argument("--revision", default=None)
    f.add_argument("--out", type=Path, required=True)

    for command in (s, v):
        command.add_argument('--task', choices=['alignment', 'segmentation', 'timing'], default='alignment')
    clips = sub.add_parser('prepare-timing', help='slice fetched audio at reviewed segment boundaries (needs ffmpeg)')
    clips.add_argument('--cases', type=Path, required=True)
    clips.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'prepare-timing':
        print(prepare_clips(args.cases, args.out))
        return 0
    if args.command == "validate":
        return 1 if _validate(args.directory, args.task) else 0
    if args.command == "fetch":
        for p in fetch(args.out, args.corpus, revision=args.revision):
            print(p)
        return 0
    if _validate(args.directory, args.task):
        return 1
    cases = load_cases(args.corpus, cases_dir=args.cases, revision=args.revision)
    if args.task == 'alignment':
        submissions, meta = load_submissions(args.directory)
    else:
        meta_path = args.directory / 'submission.json'
        meta = SubmissionMeta.model_validate_json(meta_path.read_text()) if meta_path.exists() else None
        submissions = []
        for file in sorted(args.directory.glob('*.json')):
            if file.name == 'submission.json':
                continue
            payload = json.loads(file.read_text(encoding='utf-8'))
            payload.setdefault('case_id', file.stem)
            submissions.append(MODELS[args.task].model_validate(payload))
    try:
        report = (evaluate(cases, submissions, meta, corpus_version=args.corpus) if args.task == 'alignment'
                  else evaluate_task(args.task, cases, submissions, meta, args.corpus))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.summary:
        print(f"corpus {report['corpus_version']} {report['corpus_fingerprint'][:12]}")
        for k, val in report["headline"].items():
            print(f"{k:<18} {val if not isinstance(val, float) else round(val, 4)}")
        return 0
    text = json.dumps(report, indent=1, allow_nan=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())