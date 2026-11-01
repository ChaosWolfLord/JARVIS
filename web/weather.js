// The weather widget. Forecasts come from Open-Meteo (free, no account or key). Only the place you picked (its
// coordinates) is sent there: type a city, or press "My location" and allow the browser to share where you are.

const GEO = 'https://geocoding-api.open-meteo.com/v1/search';
const FORECAST = 'https://api.open-meteo.com/v1/forecast';
const REFRESH_MS = 15 * 60 * 1000;
const KEY = 'jarvis.weather';

// Open-Meteo's weather codes (WMO) as an icon and a few words.
const CODES = {
  0: ['☀️', 'Clear'], 1: ['🌤️', 'Mostly clear'], 2: ['⛅', 'Partly cloudy'], 3: ['☁️', 'Overcast'],
  45: ['🌫️', 'Fog'], 48: ['🌫️', 'Freezing fog'],
  51: ['🌦️', 'Light drizzle'], 53: ['🌦️', 'Drizzle'], 55: ['🌧️', 'Heavy drizzle'], 56: ['🌧️', 'Freezing drizzle'], 57: ['🌧️', 'Freezing drizzle'],
  61: ['🌧️', 'Light rain'], 63: ['🌧️', 'Rain'], 65: ['🌧️', 'Heavy rain'], 66: ['🌧️', 'Freezing rain'], 67: ['🌧️', 'Freezing rain'],
  71: ['🌨️', 'Light snow'], 73: ['🌨️', 'Snow'], 75: ['❄️', 'Heavy snow'], 77: ['🌨️', 'Snow grains'],
  80: ['🌦️', 'Showers'], 81: ['🌧️', 'Heavy showers'], 82: ['⛈️', 'Violent showers'], 85: ['🌨️', 'Snow showers'], 86: ['❄️', 'Heavy snow showers'],
  95: ['⛈️', 'Thunderstorm'], 96: ['⛈️', 'Thunderstorm, hail'], 99: ['⛈️', 'Severe thunderstorm'],
};
export const describe = (code, isDay = 1) => {
  const [icon, text] = CODES[code] || ['🌡️', 'Unknown'];
  return [!isDay && (code === 0 || code === 1) ? '🌙' : icon, text];
};

export class Weather {
  constructor({ el }) {
    this.el = el;
    this.q = (s) => el.querySelector(s);
    this.place = null;
    this.units = /^en-US/i.test(navigator.language || '') ? 'f' : 'c';
    try {
      const saved = JSON.parse(localStorage.getItem(KEY));
      if (saved?.place?.lat != null) this.place = saved.place;
      if (saved?.units === 'f' || saved?.units === 'c') this.units = saved.units;
    } catch { /* first time */ }
    this.visible = false;
    this.q('#weather-gear').addEventListener('click', () => this.toggleForm());
    this.q('#weather-form').addEventListener('submit', (e) => { e.preventDefault(); this.search(this.q('#weather-q').value); });
    this.q('#weather-locate').addEventListener('click', () => this.locate());
    this.q('#weather-units').addEventListener('click', () => {
      this.units = this.units === 'f' ? 'c' : 'f';
      this.save();
      this.syncUnits();
      this.refresh();
    });
    this.syncUnits();
    setInterval(() => { if (this.visible) this.refresh(); }, REFRESH_MS);
  }

  save() {
    try { localStorage.setItem(KEY, JSON.stringify({ place: this.place, units: this.units })); } catch { /* not remembered */ }
  }

  syncUnits() { this.q('#weather-units').textContent = this.units === 'f' ? '°F' : '°C'; }

  onShow() {
    this.visible = true;
    if (this.place) this.refresh();
    else { this.toggleForm(true); this.status('Type a city to see its weather.'); }
  }

  onHide() { this.visible = false; }

  toggleForm(open = this.q('#weather-form').hidden) {
    this.q('#weather-form').hidden = !open;
    if (!open) this.q('#weather-results').hidden = true;
    else this.q('#weather-q').focus?.();
  }

  status(text) { this.q('#weather-foot').textContent = text; }

  async getJson(url) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 10_000);
    try {
      const res = await fetch(url, { signal: ctl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  async search(text) {
    const query = text.trim();
    if (!query) return;
    this.status('Looking…');
    try {
      const data = await this.getJson(`${GEO}?name=${encodeURIComponent(query)}&count=5&language=en&format=json`);
      const list = this.q('#weather-results');
      const found = data.results || [];
      list.replaceChildren(...found.map((r) => {
        const li = document.createElement('li');
        const b = Object.assign(document.createElement('button'), { type: 'button' });
        b.textContent = [r.name, r.admin1, r.country_code].filter(Boolean).join(', ');
        b.addEventListener('click', () => this.setPlace({ name: r.name, region: r.admin1 || r.country || '', lat: r.latitude, lon: r.longitude }));
        li.append(b);
        return li;
      }));
      list.hidden = !found.length;
      if (found.length) {
        const best = found[0];       // the top match is nearly always right: use it now, and offer the others in case it isn't
        this.setPlace({ name: best.name, region: best.admin1 || best.country || '', lat: best.latitude, lon: best.longitude }, found.length > 1);
        if (found.length > 1) list.prepend(Object.assign(document.createElement('li'), { className: 'w-hint', textContent: 'Showing the first match. Not the right one? Pick another:' }));
      } else {
        this.status(`No place called “${query}” was found.`);
      }
    } catch {
      this.status('Couldn’t look that up. Check the internet connection.');
    }
  }

  locate() {
    if (!navigator.geolocation) return this.status('This browser can’t share its location.');
    this.status('Waiting for your browser’s permission…');
    navigator.geolocation.getCurrentPosition(
      (pos) => this.setPlace({ name: 'My location', region: '', lat: +pos.coords.latitude.toFixed(3), lon: +pos.coords.longitude.toFixed(3) }),
      () => this.status('Location wasn’t shared. Type a city instead.'),
      { timeout: 15_000, maximumAge: 600_000 },
    );
  }

  setPlace(place, keepChoices = false) {
    this.place = place;
    this.save();
    if (!keepChoices) {
      this.q('#weather-results').hidden = true;
      this.q('#weather-form').hidden = true;
    }
    this.refresh();
  }

  async refresh() {
    if (!this.place) return;
    const { lat, lon, name } = this.place;
    this.q('#weather-title').textContent = name.toUpperCase();
    const f = this.units === 'f';
    const url = `${FORECAST}?latitude=${lat}&longitude=${lon}&timezone=auto&forecast_days=6`
      + '&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day'
      + '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'
      + `&temperature_unit=${f ? 'fahrenheit' : 'celsius'}&wind_speed_unit=${f ? 'mph' : 'kmh'}`;
    try {
      this.render(await this.getJson(url));
    } catch {
      this.status('Weather unavailable right now. Will try again.');
    }
  }

  render(d) {
    const c = d.current;
    const dayUnit = this.units === 'f' ? 'mph' : 'km/h';
    const deg = (n) => `${Math.round(n)}°`;
    const [icon, text] = describe(c.weather_code, c.is_day);
    const today = { hi: d.daily.temperature_2m_max[0], lo: d.daily.temperature_2m_min[0], rain: d.daily.precipitation_probability_max[0] };
    const body = this.q('#weather-body');
    const now = document.createElement('div');
    now.className = 'w-now';
    now.innerHTML = '<span class="w-icon"></span><span class="w-temp"></span><div><b></b><small></small><small></small></div>';
    now.querySelector('.w-icon').textContent = icon;
    now.querySelector('.w-temp').textContent = deg(c.temperature_2m);
    const [title, line1, line2] = now.querySelectorAll('b, small');
    title.textContent = text;
    line1.textContent = `Feels like ${deg(c.apparent_temperature)} · Wind ${Math.round(c.wind_speed_10m)} ${dayUnit} · Humidity ${c.relative_humidity_2m}%`;
    line2.textContent = `High ${deg(today.hi)} · Low ${deg(today.lo)}${today.rain != null ? ` · ${today.rain}% chance of rain` : ''}`;
    const days = document.createElement('div');
    days.className = 'w-days';
    for (let i = 1; i < d.daily.time.length; i++) {
      const cell = document.createElement('div');
      const name = new Date(`${d.daily.time[i]}T12:00:00`).toLocaleDateString([], { weekday: 'short' });
      cell.innerHTML = '<small></small><span></span><b></b><small></small>';
      const [a, , hi, rain] = cell.children;
      a.textContent = name;
      cell.children[1].textContent = describe(d.daily.weather_code[i])[0];
      hi.textContent = `${deg(d.daily.temperature_2m_max[i])} / ${deg(d.daily.temperature_2m_min[i])}`;
      rain.textContent = d.daily.precipitation_probability_max[i] != null ? `${d.daily.precipitation_probability_max[i]}%` : '';
      days.append(cell);
    }
    body.replaceChildren(now, days);
    this.status(`${this.place.region ? `${this.place.region} · ` : ''}Open-Meteo · updated ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`);
  }
}
