import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

class FakeAudioContext extends EventTarget {
  static instances = [];
  static resumeResults = [];
  static decodePromise = null;

  constructor() {
    super();
    this.state = 'suspended';
    this.destination = {};
    this.resumeCalls = 0;
    this.sources = [];
    FakeAudioContext.instances.push(this);
  }

  resume() {
    this.resumeCalls += 1;
    const result = FakeAudioContext.resumeResults.shift() || 'resolve';
    if (result === 'reject') return Promise.reject(new Error('blocked'));
    this.state = 'running';
    this.dispatchEvent(new Event('statechange'));
    return Promise.resolve();
  }

  createBuffer() {
    return { kind: 'silent' };
  }

  createBufferSource() {
    const source = {
      buffer: null,
      connect: vi.fn(),
      disconnect: vi.fn(),
      start: vi.fn(),
      onended: null,
    };
    this.sources.push(source);
    return source;
  }

  createGain() {
    return {
      gain: { value: 1 },
      connect: vi.fn(),
      disconnect: vi.fn(),
    };
  }

  decodeAudioData() {
    return FakeAudioContext.decodePromise || Promise.resolve({ kind: 'score' });
  }
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe('mobile score audio unlock', () => {
  let documentTarget;

  beforeEach(() => {
    vi.resetModules();
    FakeAudioContext.instances = [];
    FakeAudioContext.resumeResults = [];
    FakeAudioContext.decodePromise = null;
    documentTarget = new EventTarget();
    vi.stubGlobal('document', documentTarget);
    vi.stubGlobal('window', { AudioContext: FakeAudioContext });
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      arrayBuffer: async () => new ArrayBuffer(8),
    })));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('creates and unlocks the context from touchend, not pointerdown', async () => {
    await import('./sound');

    documentTarget.dispatchEvent(new Event('pointerdown'));
    expect(FakeAudioContext.instances).toHaveLength(0);

    documentTarget.dispatchEvent(new Event('touchend'));
    await flushPromises();

    const context = FakeAudioContext.instances[0];
    expect(context.state).toBe('running');
    expect(context.resumeCalls).toBe(1);
    expect(context.sources[0].buffer).toEqual({ kind: 'silent' });
    expect(context.sources[0].start).toHaveBeenCalledWith(0);
  });

  it('keeps gesture listeners armed after a failed resume and retries', async () => {
    FakeAudioContext.resumeResults = ['reject', 'resolve'];
    await import('./sound');

    documentTarget.dispatchEvent(new Event('touchend'));
    await flushPromises();
    const context = FakeAudioContext.instances[0];
    expect(context.state).toBe('suspended');

    documentTarget.dispatchEvent(new Event('click'));
    await flushPromises();
    expect(context.resumeCalls).toBe(2);
    expect(context.state).toBe('running');
  });

  it('plays the decoded score buffer from a later non-gesture callback', async () => {
    const sound = await import('./sound');
    documentTarget.dispatchEvent(new Event('click'));
    await flushPromises();

    const context = FakeAudioContext.instances[0];
    const sourcesBefore = context.sources.length;
    sound.playScoreSound();

    expect(context.sources).toHaveLength(sourcesBefore + 1);
    expect(context.sources.at(-1).buffer).toEqual({ kind: 'score' });
    expect(context.sources.at(-1).start).toHaveBeenCalledWith(0);
  });

  it('plays one pending score after the buffer finishes decoding', async () => {
    let finishDecode;
    FakeAudioContext.decodePromise = new Promise((resolve) => {
      finishDecode = resolve;
    });
    const sound = await import('./sound');
    documentTarget.dispatchEvent(new Event('touchend'));
    await flushPromises();

    const context = FakeAudioContext.instances[0];
    sound.playScoreSound();
    sound.playScoreSound();
    expect(context.sources).toHaveLength(1); // silent unlock source only

    finishDecode({ kind: 'score' });
    await flushPromises();

    expect(context.sources).toHaveLength(2);
    expect(context.sources.at(-1).buffer).toEqual({ kind: 'score' });
    expect(context.sources.at(-1).start).toHaveBeenCalledWith(0);
  });
});
