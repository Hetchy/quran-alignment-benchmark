<script lang="ts">export let task: string;</script>
<details class="format"><summary>View {task==='timing'?'word timing':'waqf segmentation'} format and submission instructions</summary>
  <p>Upload one JSON per recording, named <code>&lt;recording-id&gt;.json</code>. No manifest, schema version, or system metadata file is needed. All recordings in the latest corpus are required to publish.</p>
  {#if task==='segmentation'}
    <p>Input: the complete recording. Return ordered, non-overlapping speech segments at audible waqf points. Times are seconds from the recording start. No text, references, or Quran/non-Quran labels are needed. Splits wholly in non-Quran speech earn no credit.</p>
    <pre>{JSON.stringify({segments:[{start_s:5.78,end_s:12.34},{start_s:13.1,end_s:22.3}],runtime_seconds:1.8},null,2)}</pre>
    <p><code>segments: []</code> is a valid result with no predictions. Runtime is optional; report it for every recording or none, with CPU/GPU and a hardware description.</p>
  {:else}
    <p>Input: the dataset's reviewed segment clips and their supplied references, including formula segments. Use the repository utility to cut exactly at the existing segment start/end times:</p>
    <pre>qab fetch --corpus v1 --out corpus
qab prepare-timing --cases corpus --out timing-inputs</pre>
    <p>The second command needs FFmpeg. Each recording's input JSON lists clip files, references, and words in order. Do not feed reference word timestamps to your system.</p>
    <pre>{JSON.stringify({clips:[{words:[{start_s:0,end_s:.72},null]},{words:null}]},null,2)}</pre>
    <p><code>clips</code> must follow dataset segment order with exactly one entry per supplied clip. Each word array follows supplied word order and must have the exact word count. Times are relative to the clip start, in seconds, and must stay within its duration.</p>
    <p>Use <code>null</code> for an untimed word. Use <code>"words": null</code> when every word in that clip is untimed. Both count as failures. No repeated text, references, or runtime field is needed.</p>
  {/if}
  <p>For a combined ZIP, put files under <code>alignment/</code>, <code>segmentation/</code>, and <code>timing/</code>. The uploader routes each folder to its task. Preview every selected task together, then publish them with one confirmation. Only selected tasks are replaced.</p>
  <p>To score locally: <code>qab score predictions --task {task} --cases corpus --out report.json</code>. See Metrics for score definitions.</p>
</details>
