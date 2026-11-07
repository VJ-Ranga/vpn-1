import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import App from './App';

const profiles = [
  { id: '1', city: 'Chicago', country_code: 'US', transport: 'udp', virtual: false, servers: [{ host: 'chi.example', port: 1194 }] },
  { id: '2', city: 'Toronto', country_code: 'CA', transport: 'udp', virtual: false, servers: [] },
];
const settings = { transport: 'udp', theme: 'light', ipv6_protection: true, dns_protection: true, kill_switch: false, allow_lan: false, auto_reconnect: false };
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = String(input);
    const body = url.includes('profiles') ? { profiles } : url === '/api/settings' ? { settings: { ...settings, ...(options?.body ? JSON.parse(String(options.body)) : {}) }, protection: { available: true, active: false } } : url.includes('credentials') ? { configured: false } : { state: 'disconnected', duration_seconds: 0, bytes_in: 0, bytes_out: 0 };
    return { ok: true, json: async () => body } as Response;
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('renders Windows-style navigation and grouped country catalog', async () => {
  render(<App />);
  expect(await screen.findByRole('button', { name: 'Select United States' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Locations' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Log Details' })).toBeTruthy();
  expect(screen.getByPlaceholderText('Search city or country')).toBeTruthy();
  expect(screen.getByText('Best Available')).toBeTruthy();
});

it('connects only the selected city when Connect VPN is clicked', async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Select Chicago' }));
  expect(fetch).not.toHaveBeenCalledWith('/api/connect', expect.anything());
  await user.click(screen.getByRole('button', { name: 'Connect VPN' }));
  expect(fetch).toHaveBeenCalledWith('/api/connect', expect.objectContaining({ body: JSON.stringify({ profile_id: '1' }) }));
});

it('filters countries by city search and preserves favorites', async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Favorite United States' }));
  expect(localStorage.getItem('vpn-favorites')).toContain('country:US');
  await user.type(screen.getByPlaceholderText('Search city or country'), 'Toronto');
  expect(screen.queryByText('United States')).toBeNull();
  expect(screen.getByRole('button', { name: 'Select Canada' })).toBeTruthy();
});

it('saves kill switch only after backend accepts protection change', async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole('button', { name: 'Settings' }));
  await user.click(screen.getByRole('tab', { name: 'Advanced' }));
  await user.click(screen.getByRole('switch', { name: 'Kill Switch' }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/settings', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ kill_switch: true }) })));
});

it('reports helper failure instead of claiming a protected connection', async () => {
  const user = userEvent.setup();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, options) => String(input) === '/api/connect' ? { ok: false, json: async () => ({ detail: 'Install the protection helper' }) } as Response : original(input, options));
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Select Chicago' }));
  await user.click(screen.getByRole('button', { name: 'Connect VPN' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Install the protection helper');
  expect(screen.queryByText('VPN Connected')).toBeNull();
});

it('exposes account credentials without storing password in localStorage', async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole('button', { name: 'Account' }));
  await user.type(screen.getByPlaceholderText('Namecheap username'), 'user');
  await user.type(screen.getByPlaceholderText('Namecheap password'), 'test-password');
  await user.click(screen.getByRole('button', { name: 'Save credentials' }));
  expect(JSON.stringify(localStorage)).not.toContain('test-password');
});

it('passes explicitly selected endpoint with the profile', async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: 'Select Chicago' }));
  await user.selectOptions(screen.getByLabelText('Server endpoint'), 'chi.example');
  await user.click(screen.getByRole('button', { name: 'Connect VPN' }));
  expect(fetch).toHaveBeenCalledWith('/api/connect', expect.objectContaining({ body: JSON.stringify({ profile_id: '1', endpoint: 'chi.example' }) }));
});

it('shows verified Windows IPv6 blocking without claiming full protection', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, options) => ['/api/status', '/api/settings'].includes(String(input))
    ? { ok: true, json: async () => ({ state: 'connected', settings, protection: {
      available: false, active: false, platform: 'windows', ipv6_blocked: true,
    } }) } as Response : original(input, options));
  render(<App />);
  expect(await screen.findByText('IPv6 blocked · DNS / kill switch unavailable')).toBeTruthy();
  expect(await screen.findByText('VPN Connected (IPv4)')).toBeTruthy();
  expect(screen.queryByText('Network protection active')).toBeNull();
});

it('does not claim IPv6 blocking when the Windows guard is inactive', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, options) => ['/api/status', '/api/settings'].includes(String(input))
    ? { ok: true, json: async () => ({ state: 'disconnected', settings, protection: {
      available: false, active: false, platform: 'windows', ipv6_blocked: false,
    } }) } as Response : original(input, options));
  render(<App />);
  expect(await screen.findByText('IPv6 block inactive · DNS / kill switch unavailable')).toBeTruthy();
  expect(screen.queryByText('IPv6 blocked · DNS / kill switch unavailable')).toBeNull();
});
