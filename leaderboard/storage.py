"""Private immutable records. One process is the sole publisher; RAM is disposable.

Never mount a database on a bucket. Commit an entire submission as one new object,
then read it back before acknowledging it. Recursive listing rebuilds the index.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class Store:
    def __init__(self, directory: str | None = None, bucket: str | None = None):
        self.directory = Path(directory) if directory else None
        self.bucket = bucket
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)
        elif not bucket:
            raise ValueError("Configure QAB_BUCKET or QAB_STORE_DIR")

    def records(self):
        if self.directory:
            return self.visible([json.loads(p.read_text('utf-8')) for p in self.directory.glob('*.json')])
        from huggingface_hub import HfFileSystem, list_bucket_tree
        fs = HfFileSystem(skip_instance_cache=True)
        return self.visible([json.loads(fs.read_bytes(f"buckets/{self.bucket}/{item.path}"))
                for item in list_bucket_tree(self.bucket, recursive=True)
                if item.type == 'file' and item.path.startswith('submissions/') and item.path.endswith('.json')])

    @staticmethod
    def visible(objects):
        hidden = {record_id for obj in objects for record_id in obj.get('hidden_record_ids', [])}
        records = [record for obj in objects for record in obj.get('batch_records', [obj])
                   if 'metadata' in record]
        return [record for record in records if record['id'] not in hidden]

    def put(self, record):
        raw = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        name = f"{record['id']}.json"
        if self.directory:
            target = self.directory / name
            if target.exists():
                if target.read_bytes() != raw:
                    raise ValueError('Immutable record already exists')
                return
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
                temp = f.name
            os.replace(temp, target)
            if target.read_bytes() != raw:
                raise OSError('Persistence verification failed')
            return
        from huggingface_hub import HfFileSystem, batch_bucket_files
        path = f'submissions/{name}'
        with tempfile.TemporaryDirectory() as d:
            staged = Path(d) / name
            staged.write_bytes(raw)
            batch_bucket_files(self.bucket, add=[(str(staged), path)])
        # fsspec caches filesystem instances and directory listings. A reused
        # instance can falsely report the next newly-written object as missing.
        if HfFileSystem(skip_instance_cache=True).read_bytes(f'buckets/{self.bucket}/{path}') != raw:
            raise OSError('Persistence verification failed')
