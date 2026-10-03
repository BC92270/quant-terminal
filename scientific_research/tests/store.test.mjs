import test from 'node:test';
import assert from 'node:assert/strict';
import { LocalStorageResearchStore } from '../dist/index.js';

class MemoryStorage {
  map = new Map();
  get length() { return this.map.size; }
  clear() { this.map.clear(); }
  getItem(key) { return this.map.has(key) ? this.map.get(key) : null; }
  key(index) { return [...this.map.keys()][index] ?? null; }
  removeItem(key) { this.map.delete(key); }
  setItem(key, value) { this.map.set(key, String(value)); }
}

test('LocalStorageResearchStore persists and restores versioned memory', async () => {
  const storage = new MemoryStorage();
  const store = new LocalStorageResearchStore('test-srb', storage);
  await store.putPaper({
    id: 'p1', title: 'Paper', authors: [], access: 'metadata_only', domain: 'unknown', subjects: [],
    source: { provider: 'fixture', sourceId: 'x' }, ingestedAt: '2026-08-24T00:00:00.000Z'
  });
  const reloaded = new LocalStorageResearchStore('test-srb', storage);
  assert.equal((await reloaded.listPapers()).length, 1);
  assert.equal((await reloaded.snapshot()).papers, 1);
});
