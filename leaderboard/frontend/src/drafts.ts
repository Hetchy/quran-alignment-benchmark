export type Draft = {
  metadata: Record<string, any>;
  profiles: Record<string, { files: Record<string, File>; hardware: string }>;
  corpus: string;
};

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('qab-submission', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('drafts');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function localDraft(value?: Draft): Promise<Draft | undefined> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('drafts', value ? 'readwrite' : 'readonly');
      const store = tx.objectStore('drafts');
      const request = value ? store.put(value, 'current') : store.get('current');
      tx.oncomplete = () => resolve(value || request.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } finally { db.close(); }
}

// Text preserves invalid JSON too: signing in must never discard a user's files.
export async function encodeDraft(draft: Draft) {
  const profiles: Record<string, any> = {};
  for (const [key, profile] of Object.entries(draft.profiles)) {
    profiles[key] = { hardware: profile.hardware, files: await Promise.all(
      Object.values(profile.files).map(async file => ({name: file.name, text: await file.text()}))
    ) };
  }
  return {...draft, profiles};
}

export function decodeDraft(draft: any): Draft {
  const profiles: Draft['profiles'] = {};
  for (const [key, profile] of Object.entries(draft.profiles) as [string, any][]) {
    profiles[key] = {hardware: profile.hardware, files: Object.fromEntries(
      profile.files.map((f: any) => [f.name, new File([f.text], f.name, {type: 'application/json'})])
    )};
  }
  return {...draft, profiles};
}
