import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '../lib/api';

describe('pricing API client', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('aborts a request after fifteen seconds and returns a useful error', async () => {
    vi.spyOn(window, 'setTimeout').mockImplementation((handler) => {
      if (typeof handler === 'function') queueMicrotask(() => handler());
      return 1;
    });
    vi.stubGlobal(
      'fetch',
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'));
          });
        })
      )
    );

    const request = api.filters(new URLSearchParams());
    await expect(request).rejects.toThrow(
      'Pricing data request timed out.'
    );
  });
});
