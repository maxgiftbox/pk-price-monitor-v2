import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, api, isRetryableApiError } from '../lib/api';

describe('pricing API client', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('aborts a request after thirty-five seconds and returns a retryable error', async () => {
    const timeout = vi.spyOn(window, 'setTimeout').mockImplementation((handler) => {
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
      'Data request timed out.'
    );
    expect(timeout).toHaveBeenCalledWith(expect.any(Function), 35_000);
  });

  it('only retries network failures, timeouts, and service unavailable responses', () => {
    expect(isRetryableApiError(new TypeError('network failed'))).toBe(true);
    expect(isRetryableApiError(new ApiError('timeout'))).toBe(true);
    expect(isRetryableApiError(new ApiError('unavailable', 503))).toBe(true);
    expect(isRetryableApiError(new ApiError('bad request', 400))).toBe(false);
  });
});
