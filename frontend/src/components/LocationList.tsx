import { useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Search,
  Star,
  RefreshCw,
} from "lucide-react";
import type { Profile, Status } from "../types";
import { countryFlag, countryName } from "../countries";

type Props = {
  profiles: Profile[];
  status: Status;
  selected: string | null;
  selectedEndpoint: string;
  setEndpoint: (value: string) => void;
  favorites: string[];
  toggleFavorite: (key: string) => void;
  select: (id: string) => void;
  latencies: Record<string, number | null>;
  measure: () => void;
  measuring: boolean;
  refresh: () => void;
};

export function LocationList({
  profiles,
  status,
  selected,
  selectedEndpoint,
  setEndpoint,
  favorites,
  toggleFavorite,
  select,
  latencies,
  measure,
  measuring,
  refresh,
}: Props) {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState("all");
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [sort, setSort] = useState("name");
  const groups = useMemo(() => {
    const countries = new Map<string, Profile[]>();
    for (const profile of profiles) {
      if (
        !`${countryName(profile.country_code)} ${profile.city}`
          .toLowerCase()
          .includes(query.toLowerCase())
      )
        continue;
      if (
        tab === "favorites" &&
        !favorites.includes(profile.id) &&
        !favorites.includes(`country:${profile.country_code}`)
      )
        continue;
      countries.set(profile.country_code, [
        ...(countries.get(profile.country_code) || []),
        profile,
      ]);
    }
    return [...countries].sort(([a, pa], [b, pb]) =>
      sort === "ping"
        ? Math.min(...pa.map((p) => latencies[p.id] ?? Infinity)) -
            Math.min(...pb.map((p) => latencies[p.id] ?? Infinity)) ||
          countryName(a).localeCompare(countryName(b))
        : countryName(a).localeCompare(countryName(b)),
    );
  }, [profiles, query, tab, favorites, sort, latencies]);
  const star = (key: string, label: string) => (
    <button
      className={`favorite-star ${favorites.includes(key) ? "filled" : ""}`}
      aria-label={`${favorites.includes(key) ? "Unfavorite" : "Favorite"} ${label}`}
      aria-pressed={favorites.includes(key)}
      onClick={() => toggleFavorite(key)}
    >
      <Star
        size={21}
        fill={favorites.includes(key) ? "currentColor" : "none"}
      />
    </button>
  );
  const delay = (id: string) =>
    latencies[id] == null ? "—" : `${Math.round(latencies[id]!)} ms`;
  return (
    <>
      <div className="page-heading">
        <h1>Locations</h1>
        <button
          className="icon-button"
          title="Refresh locations"
          aria-label="Refresh locations"
          onClick={refresh}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="tabs" role="tablist" aria-label="Location list">
        <button
          role="tab"
          aria-selected={tab === "all"}
          onClick={() => setTab("all")}
        >
          All
        </button>
        <button
          role="tab"
          aria-selected={tab === "favorites"}
          onClick={() => setTab("favorites")}
        >
          Favorites
        </button>
        <span className="tab-count">{profiles.length} locations</span>
      </div>
      <div className="location-search">
        <Search size={17} />
        <input
          aria-label="Search locations"
          placeholder="Search city or country"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="text-button" onClick={measure} disabled={measuring}>
          {measuring ? "Measuring…" : "Measure ping"}
        </button>
      </div>
      <div className="location-columns">
        <label>
          <select
            aria-label="Sort locations"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="name">LOCATION</option>
            <option value="ping">LOWEST PING</option>
          </select>
        </label>
        <span title="Provider load data is not available">LOAD</span>
        <span title="Measured TCP handshake, not ICMP or UDP reachability">
          PING
        </span>
        <span>FAVORITE</span>
      </div>
      <div className="locations-scroll">
        {groups.map(([code, cities]) => (
          <section className="country-group" key={code}>
            <div
              className={`country-row ${cities.some((p) => p.id === selected) ? "chosen-country" : ""}`}
            >
              <button
                className="location-choice"
                aria-label={`Select ${countryName(code)}`}
                onClick={() =>
                  select(
                    [...cities].sort(
                      (a, b) =>
                        (latencies[a.id] ?? Infinity) -
                        (latencies[b.id] ?? Infinity),
                    )[0].id,
                  )
                }
              >
                <span className="country-flag">
                  {countryFlag(code === "UK" ? "GB" : code)}
                </span>
                <span>
                  <strong>{countryName(code)}</strong>
                  <small>
                    {cities.length === 1
                      ? `${cities[0].city}${cities[0].virtual ? " · Virtual" : ""}`
                      : `${cities.length} cities`}
                  </small>
                </span>
              </button>
              <span
                className="cell-muted"
                title="Not supplied by profile downloads"
              >
                —
              </span>
              <span className="cell-muted">{delay(cities[0].id)}</span>
              <div className="row-actions">
                {star(`country:${code}`, countryName(code))}
                <button
                  className="expand-button"
                  aria-label={`${collapsed.includes(code) ? "Expand" : "Collapse"} ${countryName(code)}`}
                  aria-expanded={!collapsed.includes(code)}
                  onClick={() =>
                    setCollapsed((previous) =>
                      previous.includes(code)
                        ? previous.filter((item) => item !== code)
                        : [...previous, code],
                    )
                  }
                >
                  {collapsed.includes(code) ? (
                    <ChevronRight size={17} />
                  ) : (
                    <ChevronDown size={17} />
                  )}
                </button>
              </div>
            </div>
            {!collapsed.includes(code) &&
              cities.map((profile) => (
                <div
                  className={`city-row ${selected === profile.id ? "selected" : ""}`}
                  key={profile.id}
                >
                  <button
                    className="location-choice"
                    aria-label={`Select ${profile.city}`}
                    onClick={() => select(profile.id)}
                  >
                    <span className="city-indicator">
                      {status.profile_id === profile.id &&
                      status.state === "connected" ? (
                        <CircleCheck size={17} />
                      ) : (
                        <span />
                      )}
                    </span>
                    <span>
                      <strong>{profile.city}</strong>
                      <small>
                        {profile.virtual
                          ? "Virtual location"
                          : countryName(code)}
                      </small>
                    </span>
                  </button>
                  <span className="cell-muted">—</span>
                  <span className="cell-muted">{delay(profile.id)}</span>
                  <div className="row-actions">
                    {star(profile.id, profile.city)}
                  </div>
                </div>
              ))}
          </section>
        ))}
        {!groups.length && (
          <div className="empty-state">
            <Star size={28} />
            <h2>
              {tab === "favorites"
                ? "Your favorite locations"
                : "No locations found"}
            </h2>
            <p>
              {tab === "favorites"
                ? "Select a star beside a country or city to save it here."
                : "Try a different city or country."}
            </p>
          </div>
        )}
      </div>
      {selected && <label className="endpoint-picker">Server<select aria-label="Server endpoint" value={selectedEndpoint} onChange={event => setEndpoint(event.target.value)}><option value="">Automatic (all servers)</option>{profiles.find(profile => profile.id === selected)?.servers?.map(server => <option key={server.host} value={server.host}>{server.host}:{server.port}</option>)}</select></label>}
      <div className="list-footnote">
        Load unavailable · Ping measures TCP handshake
      </div>
    </>
  );
}
