# Segmentation and word timing, task scorer 1

These tasks are independent of alignment. The alignment arithmetic and fingerprint remain unchanged. New task fingerprints include the alignment truth fingerprint plus the reviewed `segments` column. The selected corpus config (v1, v2, etc.) is loaded from the current dataset without a commit pin.

## Reference and input

Load the dataset's explicit ordered `segments[{start_s,end_s,first_word,last_word}]` alongside `truth`. Never infer segments from gaps. Assign reference words to their segment in time order and validate the first/last labels, containment, non-overlap, and exhaustive coverage. Formula segments are retained for timing. Only segments containing Quran tokens are segmentation targets.

Segmentation input is the whole recording. Timing input is one clip per existing reviewed segment, with its supplied reference and ordered word occurrences. Repeated references remain distinct occurrences. `qab prepare-timing` decodes each recording once to PCM at its original sample rate/channel count, cuts at the existing boundaries rounded to the nearest sample, and writes lossless WAVs. No additional context or padding is introduced. Cuts stop at actual audio EOF: v1's final Minshawi annotation is 36 ms beyond its audio duration. The extractor rejects reference overruns greater than the existing one-second corpus allowance.

The timing input index is one `<recording-id>.json` containing `clips[{audio,reference,words}]`; word entries are labels only, never target timestamps. The manifest records a reference fingerprint. Ground-truth case files are scorer inputs and must not be supplied to a submitted timing system.

## Prediction files

One JSON per recording ID for either task. The filename supplies `case_id`; an explicit `case_id`, if present, must agree. Unknown fields and nonfinite numbers fail validation. No user schema version or manifest is required by the Space.

Segmentation: `{"segments":[{"start_s":1,"end_s":4}],"runtime_seconds":0.2}`. Intervals must be positive, ordered, non-overlapping, and inside the recording's extent (including any existing reference endpoint overrun). Empty segments are valid, scoring missing predictions. Runtime is optional, positive, and all-or-none across recordings; it requires CPU/GPU and a hardware description.

Timing: `{"clips":[{"words":[{"start_s":0,"end_s":0.7},null]},{"words":null}]}`. Exactly one clip entry per reference segment, in the same order. Exactly one word entry per supplied occurrence, or `words: null` as shorthand for a full array of nulls. Individual nulls denote failed words. Present intervals must be positive, have nondecreasing starts, and stay inside the reference clip duration. Overlap is allowed because starts and ends are judged independently. Times are clip-relative seconds. Runtime is not accepted.

## Segmentation scoring

Constants: inward/adjacent-speech allowance `epsilon = 0.750 s`; silence padding `pad = 2.0 s`. These do not alter alignment's 0.5-second constant.

For a reference Quran segment `[a,b]`, the start window is `[max(0,a-pad,p-epsilon), a+epsilon]`; the end window is `[b-epsilon,min(D,b+pad,n+epsilon)]`. Here `p` is the nearest preceding outside word/non-Quran interval end, `n` is the nearest following outside word/non-Quran interval start, and absent neighbours impose no limit. `D` is max(audio duration, final reviewed endpoint). Formula words constrain padding like other speech. Comparisons admit floating-point slack of 1e-9 seconds.

Evaluate predictions that overlap a Quran target, including their complete extension into other speech. Ignore predictions not touching Quran when they overlap standalone formula or non-Quran speech. Otherwise, a silence-only prediction is evaluated if it intersects any target's outer window `[start lower bound,end upper bound]`. Predictions outside all evaluation regions are ignored.

A complete match requires both acceptable boundaries, predicted duration at least half the reference duration, and total overlap with non-Quran/formula-only intervals at most epsilon. Compute maximum-cardinality one-to-one matching over eligible pairs. Missing and extra segments count against recall and precision respectively. No predicted segment receives multiple complete-match credits.

For the boundary metric, separately compute maximum-cardinality start-to-start and end-to-end matching using the same windows. No duration/contamination test applies to this partial-credit diagnostic.

For either segments or boundaries, pool `matched`, `true`, and `predicted` counts. Found = matched/true; correct = matched/predicted; F1 = 2*matched/(true+predicted). A zero denominator is undefined. An empty prediction with nonempty truth has F1 zero. Rank by segments F1; equal values share rank. Undefined ranks follow the existing board's zero-equivalent ordering. RTF pools total processing seconds / total recording seconds.

## Timing scoring

Compare each predicted word with the same-position reference occurrence, subtracting the segment start from reference times. No text matching occurs. A word passes if both absolute start and end errors are at most 0.300 seconds, inclusive with 1e-9 slack. A null never passes. A clip passes only if every word passes.

Pool passing words / all words for `words_timed` (primary rank); pool passing clips / all clips for `clean_clips`. Formula clips are included. Do not average recording percentages. The detailed report repeats both metrics at 0.05, 0.1, 0.2, and 0.5 seconds, and reports mean absolute boundary error in milliseconds only when every word has a prediction; otherwise that diagnostic is undefined. No timing RTF.

## Publication and filtering

Task, corpus, files, metadata, and predecessor identity are bound by the existing signed preview proof. All selected tasks are previewed together and published with one confirmation. A single immutable batch object makes publication atomic across the selected tasks. Invalid selected tasks block the batch; users may deselect them to publish the remaining tasks. Draft files are keyed by task and CPU/GPU, including across reload/authentication handoff.

Ownership remains global to the normalized system name. Replacements are scoped to `(system, hardware class, task, latest corpus version)`; old artifacts are retained privately indefinitely. Historical versions are display-only. Public endpoints expose no prediction files, private identity, or email. Filters re-run the task scorer over the selected records and pool underlying counts.
