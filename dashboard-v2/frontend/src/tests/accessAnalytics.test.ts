import { beforeEach, expect, test, vi } from 'vitest';

import { trackDashboardAccess } from '../lib/accessAnalytics';


beforeEach(() => {
  window.sessionStorage.clear();
  vi.restoreAllMocks();
  vi.spyOn(window.crypto, 'randomUUID').mockReturnValue('7c15ec3a-7ab9-4f15-8a6c-aaf430b9a5a9');
});


test('records one session start and distinct module views', async () => {
  const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(new Response(null, { status: 202 }));

  trackDashboardAccess('/social-intelligence');
  trackDashboardAccess('/social-intelligence');
  trackDashboardAccess('/consumer-voice');

  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
    eventType: 'session_start',
    path: '/social-intelligence',
  });
  expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toMatchObject({
    eventType: 'page_view',
    path: '/consumer-voice',
  });
});


test('starts a new session after 30 minutes without navigation', () => {
  const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(new Response(null, { status: 202 }));
  vi.spyOn(Date, 'now')
    .mockReturnValueOnce(1_000)
    .mockReturnValueOnce(1_001)
    .mockReturnValueOnce(30 * 60 * 1_000 + 1_002);

  trackDashboardAccess('/social-intelligence');
  trackDashboardAccess('/social-intelligence');
  trackDashboardAccess('/social-intelligence');

  expect(fetchMock).toHaveBeenCalledTimes(4);
  expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body)).eventType).toBe('session_start');
});
