import { useMemo, useState } from 'react';
import { ArrowUpDown, Copy, Search, Star } from 'lucide-react';
import type { Profile, Status } from '../types';
import { countryFlag, countryName } from '../countries';

function EndpointList({ servers, copyServer }: { servers: Profile['servers']; copyServer: (host: string, port: number) => void }) {
  const [expanded, setExpanded] = useState(false);
  const visibleServers = expanded ? servers : servers.slice(0, 1);
  return <div className="profile-servers">
    {visibleServers.map(server => <span className="server-endpoint" key={`${server.host}:${server.port}`}>{server.host}:{server.port}<button aria-label={`Copy ${server.host}`} onClick={() => copyServer(server.host, server.port)}><Copy size={12} /></button></span>)}
    {servers.length > 1 && <button className="endpoint-toggle" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? 'Show fewer endpoints' : `+${servers.length - 1} more`}</button>}
  </div>;
}

export function ServerBrowser({ profiles, status, onConnect, busy }: { profiles: Profile[]; status: Status; onConnect: (id: string) => void; busy: boolean }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('name');
  const [favorites, setFavorites] = useState<string[]>(() => JSON.parse(localStorage.getItem('vpn-favorites') || '[]'));
  const recent = JSON.parse(localStorage.getItem('vpn-recent') || '{}') as Record<string, number>;
  const favoriteProfiles = profiles.filter(profile => favorites.includes(profile.id));
  const list = useMemo(() => profiles.filter(p => (filter === 'all' || p.transport === filter) && `${p.city} ${p.country_code} ${countryName(p.country_code)}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => {
    if (sort === 'favorite') return Number(!favorites.includes(a.id)) - Number(!favorites.includes(b.id)) || a.city.localeCompare(b.city);
    if (sort === 'recent') return (recent[b.id] || 0) - (recent[a.id] || 0) || a.city.localeCompare(b.city);
    if (sort === 'latency') return Number(a.id !== status.profile_id) - Number(b.id !== status.profile_id) || a.city.localeCompare(b.city);
    return a.city.localeCompare(b.city);
  }), [profiles, query, filter, sort, favorites, status.profile_id]);
  const toggle = (id: string) => {
    const next = favorites.includes(id) ? favorites.filter(x => x !== id) : [...favorites, id];
    setFavorites(next);
    localStorage.setItem('vpn-favorites', JSON.stringify(next));
  };
  const connect = (id: string) => {
    localStorage.setItem('vpn-recent', JSON.stringify({ ...recent, [id]: Date.now() }));
    onConnect(id);
  };
  const copyServer = (host: string, port: number) => {
    void navigator.clipboard?.writeText(`${host}:${port}`);
  };
  const servers = (profile: Profile) => profile.servers ?? [];
  return <section className="browser panel">
    <div className="section-head"><div><div className="eyebrow">SERVER INDEX / {profiles.length} NODES</div><h2>Find your route</h2></div><ArrowUpDown size={17} /></div>
     <div className="favorites-block"><div className="eyebrow"><Star size={13} /> FAVORITE LOCATIONS</div>{favoriteProfiles.length ? <div className="favorites-list">{favoriteProfiles.map(p => <div className={`favorite-card ${status.profile_id === p.id ? 'active' : ''}`} key={p.id}><div><strong><span className="flag" aria-label={`Flag for ${p.country_code}`}>{countryFlag(p.country_code)}</span>{p.city}</strong><span>{countryName(p.country_code)} · {p.transport.toUpperCase()}</span><EndpointList servers={servers(p)} copyServer={copyServer} /></div><button className="favorite-connect" disabled={busy || status.profile_id === p.id} onClick={() => connect(p.id)}>{status.profile_id === p.id ? 'ACTIVE' : 'CONNECT'}</button><button className="favorite-remove" aria-label={`Remove favorite ${p.city}`} onClick={() => toggle(p.id)}><Star size={15} fill="currentColor" /></button></div>)}</div> : <p className="favorites-empty">Star any server below for one-click access.</p>}</div>
    <div className="controls"><label className="search"><Search size={16} /><input aria-label="Search servers" placeholder="Search city or country" value={query} onChange={e => setQuery(e.target.value)} /></label><label>Sort <select aria-label="Sort servers" value={sort} onChange={e => setSort(e.target.value)}><option value="name">Name</option><option value="favorite">Favorites first</option><option value="recent">Recently used</option><option value="latency">Lowest latency</option></select></label><div className="filters">{['all', 'tcp', 'udp'].map(x => <button className={filter === x ? 'selected' : ''} key={x} onClick={() => setFilter(x)}>{x.toUpperCase()}</button>)}</div></div>
     <div className="server-list">{list.map(p => <div className={`server-row ${status.profile_id === p.id ? 'active' : ''}`} key={p.id}><button className="star" onClick={() => toggle(p.id)} aria-label={`Favorite ${p.city}`}><Star size={16} fill={favorites.includes(p.id) ? 'currentColor' : 'none'} /></button><div className="server-name"><strong><span className="flag" aria-label={`Flag for ${p.country_code}`}>{countryFlag(p.country_code)}</span>{p.city}</strong><span>{countryName(p.country_code)}{p.virtual ? ' · virtual location' : ''}</span><EndpointList servers={servers(p)} copyServer={copyServer} /></div><span className={`badge ${p.transport}`}>{p.transport}</span><button className="connect-link" disabled={busy || status.profile_id === p.id} onClick={() => connect(p.id)}>{status.profile_id === p.id ? 'ACTIVE' : 'CONNECT'}</button></div>)}</div>
  </section>;
}
