/* klingel-sprechen-card – Sprechen-Knopf fuer die Aqara-Klingel (02.10.2026)
 *
 * Tippen = Mikrofon an, nochmal tippen = aus (spaetestens nach max_sekunden).
 * Schickt NUR das Mikrofon per WebRTC an den go2rtc-Stream (Standard klingel_udp); dessen zweite Quelle
 * (exec:.../klingel_sprechen.py#backchannel=1) reicht den Ton an den Lautsprecher der Klingel weiter.
 * Das Videobild bleibt davon unberuehrt (eigene Verbindung, kein Empfang).
 * Signalisierung ueber den HA-Proxy der WebRTC-Integration (/api/webrtc/ws, signierter Pfad) -> kein Mixed Content.
 *
 * type: custom:klingel-sprechen-card
 * stream: klingel_udp        # go2rtc-Streamname
 * name: Sprechen
 * hoehe: 64                  # px
 * max_sekunden: 60
 */
class KlingelSprechenCard extends HTMLElement {
  setConfig(config) {
    this._c = Object.assign({ stream: 'klingel_udp', name: 'Sprechen', hoehe: 64, max_sekunden: 60 }, config || {});
    this._state = 'aus';
    if (this.shadowRoot) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this.shadowRoot) { this.attachShadow({ mode: 'open' }); this._render(); }
  }

  getCardSize() { return 1; }
  getGridOptions() { return { columns: 6, rows: 1 }; }
  disconnectedCallback() { this._stop(); }

  _render() {
    const h = Number(this._c.hoehe) || 64;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        button {
          all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 12px; width: 100%; height: ${h}px;
          padding: 0 16px 0 8px; border-radius: var(--bubble-button-border-radius, var(--bubble-border-radius, 32px));
          background: var(--bubble-button-main-background-color, var(--bubble-main-background-color, var(--background-color-2, var(--secondary-background-color))));
          color: var(--primary-text-color); cursor: pointer; -webkit-tap-highlight-color: transparent; overflow: hidden;
          font-family: var(--paper-font-body1_-_font-family, inherit); transition: background .2s;
        }
        .kreis { flex: 0 0 auto; width: ${h - 16}px; height: ${h - 16}px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
                 background: color-mix(in srgb, #1E88E5 22%, transparent); color: #1E88E5; }
        .text { display: flex; flex-direction: column; min-width: 0; }
        .name { font-weight: 600; font-size: 19px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .info { font-size: 13px; opacity: .75; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        button.an { background: color-mix(in srgb, #E53935 30%, var(--card-background-color, #fff)); }
        button.an .kreis { background: #E53935; color: #fff; animation: puls 1.2s ease-in-out infinite; }
        button.warte .kreis { opacity: .5; }
        button.fehler .kreis { background: color-mix(in srgb, #FB8C00 30%, transparent); color: #FB8C00; }
        @keyframes puls { 0%,100% { transform: scale(1); } 50% { transform: scale(1.12); } }
      </style>
      <button><div class="kreis"><ha-icon icon="mdi:microphone"></ha-icon></div>
        <div class="text"><div class="name"></div><div class="info" hidden></div></div></button>`;
    this._btn = this.shadowRoot.querySelector('button');
    this._btn.addEventListener('click', () => (this._state === 'aus' || this._state === 'fehler') ? this._start() : this._stop());
    this._zeige('aus');
  }

  _zeige(state, info) {
    this._state = state;
    if (!this._btn) return;
    this._btn.className = { an: 'an', warte: 'warte', fehler: 'fehler' }[state] || '';
    this.shadowRoot.querySelector('ha-icon').setAttribute('icon', state === 'an' ? 'mdi:microphone' : state === 'fehler' ? 'mdi:microphone-off' : 'mdi:microphone-outline');
    this.shadowRoot.querySelector('.name').textContent = state === 'an' ? 'Mikro an' : state === 'warte' ? 'Verbinde …' : this._c.name;
    const i = this.shadowRoot.querySelector('.info');
    const t = info || (state === 'an' ? 'Tippen zum Beenden' : '');
    i.textContent = t; i.hidden = !t;
  }

  async _start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { this._zeige('fehler', 'Kein Mikrofon-Zugriff (HTTPS/App-Freigabe)'); return; }
    this._zeige('warte');
    const lauf = this._lauf = {};
    try {
      lauf.media = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
      if (this._lauf !== lauf) { lauf.media.getTracks().forEach((t) => t.stop()); return; }
      const pc = lauf.pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
      pc.addTransceiver(lauf.media.getAudioTracks()[0], { direction: 'sendonly', streams: [lauf.media] });
      const sig = await this._hass.callWS({ type: 'auth/sign_path', path: '/api/webrtc/ws' });
      const ws = lauf.ws = new WebSocket('ws' + this._hass.hassUrl(sig.path).substring(4) + '&url=' + encodeURIComponent(this._c.stream));
      pc.addEventListener('icecandidate', (ev) => {
        if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'webrtc/candidate', value: ev.candidate ? ev.candidate.candidate : '' }));
      });
      pc.addEventListener('connectionstatechange', () => {
        if (this._lauf !== lauf) return;
        if (pc.connectionState === 'connected') {
          this._zeige('an');
          lauf.timer = setTimeout(() => this._stop(), (Number(this._c.max_sekunden) || 60) * 1000);
        } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          this._stop('Verbindung abgebrochen');
        }
      });
      ws.addEventListener('open', async () => {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        ws.send(JSON.stringify({ type: 'webrtc/offer', value: offer.sdp }));
      });
      ws.addEventListener('message', async (ev) => {
        let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
        try {
          if (m.type === 'webrtc/answer') await pc.setRemoteDescription({ type: 'answer', sdp: m.value });
          else if (m.type === 'webrtc/candidate' && m.value) await pc.addIceCandidate({ candidate: m.value, sdpMid: '0' });
          else if (m.type === 'error') this._stop(String(m.value).slice(0, 60));
        } catch (e) { console.warn('klingel-sprechen-card', e); }
      });
      ws.addEventListener('error', () => { if (this._lauf === lauf && this._state !== 'an') this._stop('Signalisierung fehlgeschlagen'); });
      lauf.wache = setTimeout(() => { if (this._lauf === lauf && this._state === 'warte') this._stop('Keine Verbindung'); }, 12000);
    } catch (e) {
      console.warn('klingel-sprechen-card', e);
      this._lauf = lauf;
      this._stop(e && e.name === 'NotAllowedError' ? 'Mikrofon nicht freigegeben' : (e && e.message ? e.message.slice(0, 60) : 'Fehler'));
    }
  }

  _stop(fehler) {
    const lauf = this._lauf;
    this._lauf = null;
    if (lauf) {
      clearTimeout(lauf.timer); clearTimeout(lauf.wache);
      try { lauf.media && lauf.media.getTracks().forEach((t) => t.stop()); } catch (e) { /* egal */ }
      try { lauf.pc && lauf.pc.close(); } catch (e) { /* egal */ }
      try { lauf.ws && lauf.ws.close(); } catch (e) { /* egal */ }
    }
    this._zeige(fehler ? 'fehler' : 'aus', fehler || '');
    if (fehler) setTimeout(() => { if (this._state === 'fehler') this._zeige('aus'); }, 6000);
  }
}
if (!customElements.get('klingel-sprechen-card')) customElements.define('klingel-sprechen-card', KlingelSprechenCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: 'klingel-sprechen-card', name: 'Klingel Sprechen', description: 'Sprechen-Knopf: Mikrofon per WebRTC an den Rueckkanal der Aqara-Klingel' });
