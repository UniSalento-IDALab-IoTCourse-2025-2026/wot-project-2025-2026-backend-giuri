// ============================================================
// CardioSense — app.js
// Dashboard medico: MQTT WebSocket + polling REST ibrido
// ============================================================

const API    = 'https://localhost:8443';
const BROKER = 'wss://localhost:9002'; 
const TOPIC_ALLARMI = 'cardiosense/allarmi';

// ============================================================
// STATO GLOBALE
// ============================================================

let token        = localStorage.getItem('cs_token');
let medicoNome   = '';
let pazienti     = [];          // cache lista pazienti
let episodi      = [];          // cache episodi anomalia non validati (aggregati)
let validazioneCorrente = null; // { ids: [...], data, modalita } per il modal
                                // modalita: 'valida' | 'storico'

// Contatori per i KPI
let kpiValidateOggi = 0;

// Notifiche desktop — toggle lato JS
// (il permesso OS non è revocabile da codice, ma possiamo
//  smettere di chiamare new Notification() quando disattivate)
let notificheAbilitate = false;

// ============================================================
// GUARD: redirect se non autenticato
// ============================================================

if (!token) {
    window.location.href = 'index.html';
}

// ============================================================
// UTILITY — fetch autenticata
// ============================================================

async function apiFetch(path, options = {}) {
    const res = await fetch(`${API}${path}`, {
        ...options,
        headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
            ...(options.headers || {})
        }
    });
    if (res.status === 401) {
        localStorage.removeItem('cs_token');
        window.location.href = 'index.html';
        return null;
    }
    return res;
}

// ============================================================
// TOAST
// ============================================================

function showToast(tipo, titolo, messaggio, durata = 6000) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${tipo}`;
    toast.innerHTML = `
        <div class="toast-icon">${tipo === 'alarm' ? '⚠' : '✓'}</div>
        <div class="toast-body">
            <div class="toast-title">${titolo}</div>
            <div class="toast-msg">${messaggio}</div>
        </div>
    `;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), durata);
}

// ============================================================
// AUDIO — beep di allarme
// ============================================================

function suonaAllarme() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const beep = (freq, start, dur) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = freq;
            osc.type = 'sine';
            gain.gain.setValueAtTime(0.3, ctx.currentTime + start);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + dur);
            osc.start(ctx.currentTime + start);
            osc.stop(ctx.currentTime + start + dur);
        };
        beep(880, 0,    0.15);
        beep(880, 0.2,  0.15);
        beep(1100, 0.4, 0.3);
    } catch (e) {
        // AudioContext non disponibile (es. tab in background)
    }
}

// ============================================================
// NAVIGAZIONE — sezioni
// ============================================================

const SEZIONI = ['panoramica', 'anomalie', 'pazienti', 'storico'];

function navigaA(sezione) {
    SEZIONI.forEach(s => {
        document.getElementById(`section-${s}`)?.classList.remove('active');
        document.querySelector(`[data-section="${s}"]`)?.classList.remove('active');
    });
    document.getElementById(`section-${sezione}`)?.classList.add('active');
    document.querySelector(`[data-section="${sezione}"]`)?.classList.add('active');

    const titoli = {
        panoramica: 'Panoramica',
        anomalie:   'Anomalie da validare',
        pazienti:   'Pazienti',
        storico:    'Storico anomalie'
    };
    document.getElementById('topbar-title').textContent = titoli[sezione] || sezione;

    // Carica dati contestuali
    if (sezione === 'anomalie')  caricaEpisodi();
    if (sezione === 'pazienti')  caricaPazienti();
    if (sezione === 'storico')   popolaSelectStorico();
}

document.querySelectorAll('.nav-item[data-section]').forEach(el => {
    el.addEventListener('click', () => navigaA(el.dataset.section));
});

document.getElementById('link-vedi-tutte')?.addEventListener('click', () => {
    navigaA('anomalie');
});

// ============================================================
// SIDEBAR — info medico
// ============================================================

async function caricaProfiloMedico() {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        const email = payload.sub || '';
        medicoNome = email.split('@')[0];

        const nome = medicoNome.charAt(0).toUpperCase() + medicoNome.slice(1);
        document.getElementById('sidebar-name').textContent = `Dr. ${nome}`;
        document.getElementById('sidebar-avatar').textContent = nome.charAt(0).toUpperCase();
    } catch (e) {
        document.getElementById('sidebar-name').textContent = 'Medico';
    }
}

document.getElementById('btn-logout')?.addEventListener('click', () => {
    localStorage.removeItem('cs_token');
    window.location.href = 'index.html';
});

// ============================================================
// NOTIFICHE DI SISTEMA (Web Notifications API)
// ============================================================
// A differenza del toast in pagina, queste appaiono come notifica
// nativa di Windows/macOS anche se la tab non è in primo piano
// (basta che il browser sia aperto). Richiede HTTPS o localhost
// e il permesso esplicito dell'utente.
//
// NOTA SUL TOGGLE: il permesso OS non è revocabile via JavaScript
// per scelta intenzionale del browser (sicurezza). Il toggle lato
// JS agisce sulla variabile notificheAbilitate: quando false,
// mostraNotificaSistema() esce subito senza creare nulla.
// Stessa strategia usata da Slack, Gmail, ecc.

function aggiornaBottoneNotifiche() {
    const btn = document.getElementById('btn-notifiche');
    if (!btn) return;

    if (!('Notification' in window)) {
        btn.textContent = '🔕 Non supportate';
        btn.disabled = true;
        return;
    }

    if (Notification.permission === 'denied') {
        btn.textContent = '🔕 Bloccate (sblocca dal browser)';
        notificheAbilitate = false;
        return;
    }

    if (Notification.permission === 'granted' && notificheAbilitate) {
        btn.textContent = '🔔 Notifiche attive — clicca per disattivare';
    } else {
        btn.textContent = '🔔 Attiva notifiche desktop';
    }
}

async function richiediPermessoNotifiche() {
    if (!('Notification' in window)) {
        showToast('alarm', 'Non supportate', 'Questo browser non supporta le notifiche di sistema');
        return;
    }

    if (Notification.permission === 'denied') {
        showToast('alarm', 'Permesso negato',
            'Clicca sull\'icona del lucchetto nella barra degli indirizzi → Notifiche → Consenti, poi ricarica la pagina');
        return;
    }

    // Se il permesso è già concesso e le notifiche sono attive → disattiva (toggle off)
    if (Notification.permission === 'granted' && notificheAbilitate) {
        notificheAbilitate = false;
        aggiornaBottoneNotifiche();
        showToast('success', 'Notifiche disattivate', 'Non riceverai più notifiche desktop per i nuovi allarmi');
        return;
    }

    // Prima richiesta o riattivazione dopo disattivazione
    if (Notification.permission === 'default') {
        await Notification.requestPermission();
    }

    if (Notification.permission === 'granted') {
        notificheAbilitate = true;
        aggiornaBottoneNotifiche();
        // Notifica di TEST immediata — se non la vedi ora,
        // il problema è nel browser/OS, non nella pipeline degli allarmi.
        mostraNotificaSistema(
            '✓ Notifiche desktop attive',
            'Riceverai una notifica per ogni nuovo episodio di anomalia rilevato.'
        );
    } else if (Notification.permission === 'denied') {
        notificheAbilitate = false;
        aggiornaBottoneNotifiche();
        showToast('alarm', 'Permesso negato',
            'Clicca sull\'icona del lucchetto nella barra degli indirizzi → Notifiche → Consenti, poi ricarica la pagina');
    }
}

function mostraNotificaSistema(titolo, corpo, tagFisso = null) {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    if (!notificheAbilitate) return;   // rispetta il toggle lato JS

    try {
        const notif = new Notification(titolo, {
            body: corpo,
            tag: tagFisso || ('cardiosense-' + Date.now()),
            requireInteraction: true
        });

        notif.onclick = () => {
            window.focus();
            navigaA('anomalie');
            notif.close();
        };

        notif.onerror = (e) => {
            console.error('Errore notifica di sistema:', e);
            showToast('alarm', 'Errore notifica', 'Controlla la console (F12) per i dettagli');
        };
    } catch (e) {
        console.error('Eccezione creando la notifica:', e);
        showToast('alarm', 'Errore notifica', e.message);
    }
}

document.getElementById('btn-notifiche')?.addEventListener('click', richiediPermessoNotifiche);

// ============================================================
// MQTT — connessione WebSocket
// ============================================================
//
// NOTA SUL DEBOUNCE: il backend pubblica un messaggio di allarme per
// OGNI lettura anomala (non per episodio — il raggruppamento avviene
// solo lato dashboard/validazione). Un episodio di 30s a 1 msg/s
// produce quindi ~30 messaggi MQTT consecutivi sullo stesso paziente.
// Per evitare 30 beep/notifiche sovrapposte per lo stesso evento
// clinico, qui teniamo un debounce per paziente: il beep/notifica
// scatta solo se sono passati almeno DEBOUNCE_ALLARME_MS dall'ultimo
// allarme per quel paziente. Il toast e il contatore KPI restano
// invece per ogni messaggio, così il medico vede comunque che il
// flusso dati continua ad arrivare.

const DEBOUNCE_ALLARME_MS = 15000;  // 15s — coerente con il gap di clustering lato backend
let ultimoAllarmePerPaziente = {};  // paziente_id -> timestamp ms dell'ultimo beep/notifica

let mqttClient = null;

function connettiBroker() {
    const dot   = document.getElementById('mqtt-dot');
    const label = document.getElementById('mqtt-label');

    dot.className   = 'status-dot connecting';
    label.textContent = 'Connessione MQTT...';

    mqttClient = mqtt.connect(BROKER, {
        clientId: `dashboard_${Math.random().toString(16).slice(2, 8)}`,
        clean: true,
        reconnectPeriod: 3000
    });

    mqttClient.on('connect', () => {
        dot.className     = 'status-dot connected';
        label.textContent = 'MQTT connesso';

        mqttClient.subscribe(TOPIC_ALLARMI, { qos: 1 });
    });

    mqttClient.on('error', () => {
        dot.className     = 'status-dot disconnected';
        label.textContent = 'MQTT disconnesso';
    });

    mqttClient.on('offline', () => {
        dot.className     = 'status-dot disconnected';
        label.textContent = 'MQTT offline';
    });

    mqttClient.on('reconnect', () => {
        dot.className     = 'status-dot connecting';
        label.textContent = 'Riconnessione...';
    });

    mqttClient.on('message', (topic, payload) => {
        if (topic !== TOPIC_ALLARMI) return;

        try {
            const msg = JSON.parse(payload.toString());
            gestisciAllarme(msg);
        } catch (e) {
            console.error('Errore parsing MQTT:', e);
        }
    });
}

function gestisciAllarme(msg) {
    const ts = msg.timestamp
        ? new Date(msg.timestamp).toLocaleTimeString('it-IT')
        : 'adesso';

    const pazienteId = msg.paziente_id || 'sconosciuto';
    const adesso = Date.now();
    const ultimoAllarme = ultimoAllarmePerPaziente[pazienteId] || 0;
    const nuovoEpisodio = (adesso - ultimoAllarme) > DEBOUNCE_ALLARME_MS;

    if (nuovoEpisodio) {
        suonaAllarme();
        mostraNotificaSistema(
            `⚠ Anomalia ECG — Paziente ${pazienteId}`,
            `Score: ${(msg.ecg_score * 100).toFixed(0)}% · Temp: ${msg.temperatura_label} · ${ts}`,
            `cardiosense-episodio-${pazienteId}`
        );
    }
    ultimoAllarmePerPaziente[pazienteId] = adesso;

    showToast(
        'alarm',
        `⚠ Anomalia ECG — Paziente ${pazienteId}`,
        `Score: ${(msg.ecg_score * 100).toFixed(0)}% · Temp: ${msg.temperatura_label} · ${ts}`,
        3000
    );

    document.getElementById('kpi-ultimo').textContent = ts;
    document.getElementById('kpi-ultimo-meta').textContent =
        `Paziente ${pazienteId}`;

    if (nuovoEpisodio) {
        aggiornaContatoreBadge(1);
    }

    const sezioneAttiva = document.querySelector('.section.active')?.id;
    if (sezioneAttiva === 'section-anomalie' || sezioneAttiva === 'section-panoramica') {
        setTimeout(caricaEpisodi, 800);
    }
}

// ============================================================
// POLLING REST — episodi di anomalia ogni 8 secondi
// ============================================================

async function caricaEpisodi() {
    const res = await apiFetch('/anomalie/episodi');
    if (!res || !res.ok) return;

    episodi = await res.json();

    const count = episodi.length;
    document.getElementById('kpi-anomalie').textContent = count;
    aggiornaContatoreBadge(count, true);

    renderTabellaEpisodiCompatta(episodi.slice(0, 5));
    renderTabellaEpisodi(episodi);
}

function aggiornaContatoreBadge(n, setAssoluto = false) {
    const badge = document.getElementById('badge-anomalie');
    const corrente = parseInt(badge.textContent) || 0;
    const nuovo = setAssoluto ? n : corrente + n;
    badge.textContent = nuovo;
    badge.classList.toggle('visible', nuovo > 0);
}

// ============================================================
// HELPER — label paziente con nome/cognome se disponibili
// ============================================================

function labelPaziente(ep) {
    if (ep.paziente_nome && ep.paziente_cognome) {
        return `${ep.paziente_nome} ${ep.paziente_cognome}
            <span style="display:block;font-family:var(--mono);font-size:0.7rem;color:var(--text-muted)">${ep.paziente_id}</span>`;
    }
    return `<span style="font-family:var(--mono);font-size:0.8rem">${ep.paziente_id}</span>`;
}

// ============================================================
// HELPER — intervallo temporale e durata di un episodio
// ============================================================

function formatIntervalloEpisodio(ep) {
    const inizio = formatTs(ep.timestamp_inizio);
    if (ep.numero_letture <= 1) {
        return inizio;
    }
    const fine = new Date(ep.timestamp_fine).toLocaleTimeString('it-IT', {
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
    return `${inizio} → ${fine}`;
}

function formatDurataEpisodio(ep) {
    if (ep.numero_letture <= 1) return '';
    const secondi = Math.round(
        (new Date(ep.timestamp_fine) - new Date(ep.timestamp_inizio)) / 1000
    );
    return `${secondi}s · ${ep.numero_letture} letture`;
}

// ============================================================
// RENDER — tabella episodi (panoramica, max 5)
// ============================================================

function renderTabellaEpisodiCompatta(lista) {
    const tbody = document.getElementById('panoramica-tbody');
    if (!tbody) return;

    if (lista.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6">
            <div class="empty-state"><div class="empty-icon">◎</div>Nessuna anomalia in attesa</div>
        </td></tr>`;
        return;
    }

    tbody.innerHTML = lista.map(ep => `
        <tr>
            <td>${labelPaziente(ep)}</td>
            <td>
                <span class="pill pill-red">anomalo</span>
                ${ep.numero_letture > 1
                    ? `<span style="display:block;font-size:0.68rem;color:var(--text-muted);margin-top:0.2rem">${formatDurataEpisodio(ep)}</span>`
                    : ''}
            </td>
            <td><span class="pill pill-muted">${ep.postura_label || '—'}</span></td>
            <td>${renderTempPill(ep.temperatura_label)}</td>
            <td style="font-size:0.75rem;color:var(--text-muted);font-family:var(--mono)">${formatIntervalloEpisodio(ep)}</td>
            <td>
                <button class="btn btn-teal" style="font-size:0.72rem;padding:0.3rem 0.7rem"
                    onclick='apriModalEpisodio(${JSON.stringify(ep).replace(/'/g, "&apos;")})'>
                    Valida
                </button>
            </td>
        </tr>
    `).join('');
}

// ============================================================
// RENDER — tabella episodi (sezione completa)
// ============================================================

function renderTabellaEpisodi(lista) {
    const tbody = document.getElementById('anomalie-tbody');
    if (!tbody) return;

    if (lista.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6">
            <div class="empty-state"><div class="empty-icon">✓</div>Nessuna anomalia in attesa</div>
        </td></tr>`;
        return;
    }

    tbody.innerHTML = lista.map(ep => `
        <tr>
            <td>${labelPaziente(ep)}</td>
            <td>
                <div style="display:flex;align-items:center;gap:0.5rem">
                    <span class="pill pill-red">anomalo</span>
                    <span style="font-family:var(--mono);font-size:0.72rem;color:var(--text-muted)">${(ep.ecg_score_max * 100).toFixed(0)}% picco</span>
                </div>
                ${ep.numero_letture > 1
                    ? `<div style="font-size:0.7rem;color:var(--text-muted);margin-top:0.25rem">${formatDurataEpisodio(ep)} · media ${(ep.ecg_score_medio * 100).toFixed(0)}%</div>`
                    : ''}
            </td>
            <td><span class="pill pill-muted">${ep.postura_label || '—'}</span></td>
            <td>${renderTempPill(ep.temperatura_label)}</td>
            <td style="font-size:0.75rem;color:var(--text-muted);font-family:var(--mono)">${formatIntervalloEpisodio(ep)}</td>
            <td>
                <button class="btn btn-teal" style="font-size:0.72rem;padding:0.3rem 0.7rem"
                    onclick='apriModalEpisodio(${JSON.stringify(ep).replace(/'/g, "&apos;")})'>
                    Valida${ep.numero_letture > 1 ? ` (${ep.numero_letture})` : ''}
                </button>
            </td>
        </tr>
    `).join('');
}

// ============================================================
// PAZIENTI
// ============================================================

async function caricaPazienti() {
    const res = await apiFetch('/pazienti');
    if (!res || !res.ok) return;

    pazienti = await res.json();
    document.getElementById('kpi-pazienti').textContent = pazienti.length;

    renderGrigliaPazienti(pazienti);
    popolaSelectStorico();
}

function renderGrigliaPazienti(lista) {
    const grid = document.getElementById('patient-grid');
    if (!grid) return;

    if (lista.length === 0) {
        grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
            <div class="empty-icon">◎</div>Nessun paziente registrato
        </div>`;
        return;
    }

    grid.innerHTML = lista.map(p => `
        <div class="patient-card">
            <div class="patient-header">
                <div class="patient-avatar">${p.nome.charAt(0)}${p.cognome.charAt(0)}</div>
                <div>
                    <div class="patient-name">${p.nome} ${p.cognome}</div>
                    <div class="patient-code">${p.codice_accesso}</div>
                </div>
            </div>
            <div class="patient-meta">
                <div class="patient-meta-row">
                    <span class="patient-meta-key">Codice accesso</span>
                    <span style="font-family:var(--mono);font-size:0.78rem;color:var(--teal)">${p.codice_accesso}</span>
                </div>
                <div class="patient-meta-row">
                    <span class="patient-meta-key">ID interno</span>
                    <span style="font-family:var(--mono);font-size:0.72rem;color:var(--text-muted)">#${p.id}</span>
                </div>
            </div>
        </div>
    `).join('');
}

// ── Modale nuovo paziente ──────────────────────────────────

document.getElementById('btn-nuovo-paziente')?.addEventListener('click', () => {
    document.getElementById('modal-paziente-overlay').classList.add('open');
    document.getElementById('codice-generato').style.display = 'none';
    document.getElementById('input-nome').value = '';
    document.getElementById('input-cognome').value = '';
    document.getElementById('btn-crea-paziente').style.display = 'inline-flex';
});

function chiudiModalPaziente() {
    document.getElementById('modal-paziente-overlay').classList.remove('open');
}

async function creaPaziente() {
    const nome    = document.getElementById('input-nome').value.trim();
    const cognome = document.getElementById('input-cognome').value.trim();

    if (!nome || !cognome) {
        showToast('alarm', 'Dati mancanti', 'Inserisci nome e cognome del paziente');
        return;
    }

    const btn = document.getElementById('btn-crea-paziente');
    btn.textContent = 'Creazione...';
    btn.disabled = true;

    const res = await apiFetch('/pazienti', {
        method: 'POST',
        body: JSON.stringify({ nome, cognome })
    });

    btn.textContent = 'Crea paziente';
    btn.disabled = false;

    if (!res || !res.ok) {
        showToast('alarm', 'Errore', 'Impossibile creare il paziente');
        return;
    }

    const paziente = await res.json();

    document.getElementById('codice-generato').style.display = 'block';
    document.getElementById('codice-value').textContent = paziente.codice_accesso;
    document.getElementById('btn-crea-paziente').style.display = 'none';

    showToast('success', 'Paziente creato', `${paziente.nome} ${paziente.cognome} — codice: ${paziente.codice_accesso}`);

    await caricaPazienti();
}

// ============================================================
// STORICO — episodi anomali per paziente (validati + in attesa)
// ============================================================

function popolaSelectStorico() {
    const sel = document.getElementById('storico-select');
    if (!sel) return;

    const corrente = sel.value;
    sel.innerHTML = '<option value="">— Seleziona paziente —</option>';
    pazienti.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.codice_accesso;
        opt.textContent = `${p.nome} ${p.cognome} (${p.codice_accesso})`;
        sel.appendChild(opt);
    });
    if (corrente) sel.value = corrente;
}

document.getElementById('btn-carica-storico')?.addEventListener('click', async () => {
    const sel = document.getElementById('storico-select');
    const pazienteId = sel?.value;

    if (!pazienteId) {
        showToast('alarm', 'Seleziona paziente', 'Scegli un paziente dalla lista');
        return;
    }

    // Usa l'endpoint pubblico episodi — include validati + in attesa
    // È pubblico (no auth) ma funziona anche dalla dashboard medico
    const res = await fetch(`${API}/pazienti/by-codice/${pazienteId}/episodi`);
    if (!res || !res.ok) {
        showToast('alarm', 'Errore', 'Impossibile caricare lo storico anomalie');
        return;
    }

    const episodiStorico = await res.json();
    renderStoricoEpisodi(episodiStorico, pazienteId);
});

/**
 * Renderizza la lista degli episodi anomali (tutti: validati + in attesa)
 * come card cliccabili nella sezione storico.
 */
function renderStoricoEpisodi(lista, pazienteId) {
    const container = document.getElementById('storico-lista-container');
    const countEl   = document.getElementById('storico-count');

    if (!container) return;

    // Trova dati paziente dalla cache locale
    const paz = pazienti.find(p => p.codice_accesso === pazienteId);
    const nomePaziente = paz ? `${paz.nome} ${paz.cognome}` : pazienteId;

    countEl.textContent = lista.length > 0
        ? `${lista.length} episodio${lista.length !== 1 ? 'i' : ''} trovato${lista.length !== 1 ? 'i' : ''}`
        : '';

    if (lista.length === 0) {
        container.innerHTML = `
            <div class="live-panel">
                <div class="table-wrap">
                    <div class="empty-state">
                        <div class="empty-icon">✓</div>
                        Nessuna anomalia registrata per ${nomePaziente}
                    </div>
                </div>
            </div>`;
        return;
    }

    // Ordina: più recenti prima (il backend già lo fa, ma per sicurezza)
    const ordinati = [...lista].sort(
        (a, b) => new Date(b.timestamp_fine) - new Date(a.timestamp_fine)
    );

    const items = ordinati.map(ep => {
        const esito = ep.esito_medico;
        let classeEsito, iconaEsito, testoEsito;

        if (esito === 'vero_positivo') {
            classeEsito = 'validato-vp';
            iconaEsito  = '✅';
            testoEsito  = '<span class="pill pill-red">Vero positivo</span>';
        } else if (esito === 'falso_allarme') {
            classeEsito = 'validato-fa';
            iconaEsito  = '❌';
            testoEsito  = '<span class="pill pill-teal">Falso allarme</span>';
        } else {
            classeEsito = 'in-attesa';
            iconaEsito  = '⏳';
            testoEsito  = '<span class="pill pill-amber">In attesa</span>';
        }

        const durataStr = ep.numero_letture > 1
            ? `<span style="font-size:0.7rem;color:var(--text-muted)">${formatDurataEpisodio(ep)}</span>`
            : '';

        return `
            <div class="storico-episodio ${classeEsito}"
                 onclick='apriModalStorico(${JSON.stringify(ep).replace(/'/g, "&apos;")})'>
                <div style="font-size:1.1rem;flex-shrink:0">${iconaEsito}</div>
                <div class="storico-ep-info">
                    <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap">
                        <span class="pill pill-red" style="font-size:0.68rem">anomalo</span>
                        <span style="font-family:var(--mono);font-size:0.72rem;color:var(--text-muted)">${(ep.ecg_score_max * 100).toFixed(0)}% picco</span>
                        ${durataStr}
                    </div>
                    <div class="storico-ep-ts">${formatIntervalloEpisodio(ep)}</div>
                    ${ep.note_medico ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:0.1rem;font-style:italic">"${ep.note_medico}"</div>` : ''}
                </div>
                <div class="storico-ep-esito">${testoEsito}</div>
                <div class="storico-ep-arrow">›</div>
            </div>
        `;
    }).join('');

    container.innerHTML = `<div class="storico-lista">${items}</div>`;
}

// ============================================================
// MODAL — validazione episodio (nuove anomalie)
// ============================================================

let esitoSelezionato = null;

/**
 * Apre il modal in modalità "valida": episodio non ancora validato
 * proveniente dalla sezione Anomalie.
 */
function apriModalEpisodio(ep) {
    validazioneCorrente = { ids: ep.annotation_ids, data: ep, modalita: 'valida' };
    esitoSelezionato = null;

    _popolaModalHeader(ep, 'Valida anomalia ECG');

    // Nascondi banner esito — non è ancora stato validato
    document.getElementById('modal-esito-banner').style.display = 'none';

    _popolaModalDettagli(ep);

    // Reset selezione esito
    document.getElementById('btn-vp').className = 'esito-btn';
    document.getElementById('btn-fa').className = 'esito-btn';
    document.getElementById('modal-note').value = '';

    // Testo bottone conferma
    const btnConferma = document.getElementById('btn-conferma-validazione');
    btnConferma.textContent = 'Conferma validazione';

    document.getElementById('modal-overlay').classList.add('open');
}

/**
 * Apre il modal in modalità "storico": episodio già validato o in attesa,
 * proveniente dalla sezione Storico. Permette di vedere il dettaglio
 * e di modificare/aggiungere la validazione.
 */
function apriModalStorico(ep) {
    validazioneCorrente = { ids: ep.annotation_ids, data: ep, modalita: 'storico' };
    esitoSelezionato = ep.esito_medico || null;  // pre-seleziona esito esistente

    _popolaModalHeader(ep, 'Dettaglio episodio ECG');

    // Banner stato esito
    const banner = document.getElementById('modal-esito-banner');
    if (ep.esito_medico === 'vero_positivo') {
        banner.className = 'esito-banner vp';
        banner.innerHTML = `
            <div>
                <div>✅ Anomalia confermata come vero positivo</div>
                ${ep.validato_at
                    ? `<div class="esito-banner-note">Validato il ${formatTs(ep.validato_at)}</div>`
                    : ''}
            </div>`;
    } else if (ep.esito_medico === 'falso_allarme') {
        banner.className = 'esito-banner fa';
        banner.innerHTML = `
            <div>
                <div>❌ Classificato come falso allarme</div>
                ${ep.validato_at
                    ? `<div class="esito-banner-note">Validato il ${formatTs(ep.validato_at)}</div>`
                    : ''}
            </div>`;
    } else {
        banner.className = 'esito-banner attesa';
        banner.innerHTML = `<div>⏳ In attesa di validazione medica</div>`;
    }
    banner.style.display = 'flex';

    _popolaModalDettagli(ep);

    // Pre-seleziona esito se già presente
    document.getElementById('btn-vp').className =
        'esito-btn' + (esitoSelezionato === 'vero_positivo' ? ' selected-vp' : '');
    document.getElementById('btn-fa').className =
        'esito-btn' + (esitoSelezionato === 'falso_allarme' ? ' selected-fa' : '');

    // Pre-popola note
    document.getElementById('modal-note').value = ep.note_medico || '';

    // Testo bottone: "Modifica" se già validato, "Conferma" se in attesa
    const btnConferma = document.getElementById('btn-conferma-validazione');
    btnConferma.textContent = ep.esito_medico
        ? 'Aggiorna validazione'
        : 'Conferma validazione';

    document.getElementById('modal-overlay').classList.add('open');
}

/**
 * Popola header del modal (titolo + info paziente).
 */
function _popolaModalHeader(ep, titolo) {
    document.getElementById('modal-title').textContent = titolo;

    const intestazione = (ep.paziente_nome && ep.paziente_cognome)
        ? `${ep.paziente_nome} ${ep.paziente_cognome} (${ep.paziente_id})`
        : ep.paziente_id;
    document.getElementById('modal-paziente-info').textContent = `Paziente: ${intestazione}`;
}

/**
 * Popola la sezione dettagli del modal (grafico ECG + dati clinici).
 * Usato sia da apriModalEpisodio che da apriModalStorico.
 */
function _popolaModalDettagli(ep) {
    const rigaDurata = ep.numero_letture > 1
        ? `
            <div class="modal-info-row">
                <span class="modal-info-key">Episodio</span>
                <span>${ep.numero_letture} letture consecutive · ${formatDurataEpisodio(ep)}</span>
            </div>
        `
        : '';

    document.getElementById('modal-details').innerHTML = `
        <div id="modal-ecg-esteso">${renderGraficoECGEsteso(scegliDocumentoPerGrafico(ep))}</div>
        ${rigaDurata}
        <div class="modal-info-row">
            <span class="modal-info-key">ECG Score${ep.numero_letture > 1 ? ' (picco / medio)' : ''}</span>
            <span class="pill pill-red">
                ${(ep.ecg_score_max * 100).toFixed(1)}%${ep.numero_letture > 1 ? ` / ${(ep.ecg_score_medio * 100).toFixed(1)}%` : ''}
            </span>
        </div>
        <div class="modal-info-row">
            <span class="modal-info-key">Postura</span>
            <span>${ep.postura_label || '—'}</span>
        </div>
        <div class="modal-info-row">
            <span class="modal-info-key">Temperatura</span>
            <span>${ep.temperatura_valore}°C — ${ep.temperatura_label}</span>
        </div>
        <div class="modal-info-row">
            <span class="modal-info-key">${ep.numero_letture > 1 ? 'Periodo' : 'Timestamp'}</span>
            <span style="font-family:var(--mono);font-size:0.78rem">${formatIntervalloEpisodio(ep)}</span>
        </div>
    `;
}

/**
 * Per il grafico ECG esteso nel modal usiamo il documento del cluster
 * con lo score più alto (il momento clinicamente più rilevante
 * dell'episodio), non semplicemente il primo o l'ultimo.
 */
function scegliDocumentoPerGrafico(ep) {
    const documenti = ep.documenti || [];
    if (documenti.length === 0) return ep;
    return documenti.reduce(
        (migliore, doc) => (doc.ecg_score > migliore.ecg_score ? doc : migliore),
        documenti[0]
    );
}

function chiudiModal() {
    document.getElementById('modal-overlay').classList.remove('open');
    validazioneCorrente = null;
    esitoSelezionato = null;
}

function selezionaEsito(esito) {
    esitoSelezionato = esito;
    document.getElementById('btn-vp').className =
        'esito-btn' + (esito === 'vero_positivo' ? ' selected-vp' : '');
    document.getElementById('btn-fa').className =
        'esito-btn' + (esito === 'falso_allarme' ? ' selected-fa' : '');
}

async function confermaValidazione() {
    if (!esitoSelezionato) {
        showToast('alarm', 'Seleziona esito', 'Scegli "Vero positivo" o "Falso allarme"');
        return;
    }

    if (!validazioneCorrente) return;

    const note = document.getElementById('modal-note').value.trim() || null;
    const btn  = document.getElementById('btn-conferma-validazione');
    const testoOriginale = btn.textContent;
    btn.textContent = 'Salvataggio...';
    btn.disabled = true;

    const numeroLetture = validazioneCorrente.ids.length;
    const res = await apiFetch('/anomalie/episodi/valida', {
        method: 'PATCH',
        body: JSON.stringify({
            annotation_ids: validazioneCorrente.ids,
            esito: esitoSelezionato,
            note
        })
    });

    btn.textContent = testoOriginale;
    btn.disabled = false;

    if (!res || !res.ok) {
        showToast('alarm', 'Errore', 'Impossibile salvare la validazione');
        return;
    }

    chiudiModal();

    const eraGiaValidato = validazioneCorrente?.data?.esito_medico;

    if (!eraGiaValidato) {
        kpiValidateOggi++;
        document.getElementById('kpi-validate').textContent = kpiValidateOggi;
    }

    const messaggioBase = esitoSelezionato === 'vero_positivo'
        ? 'Anomalia confermata — dati inviati al ri-addestramento'
        : 'Falso allarme registrato';
    const suffissoEpisodio = numeroLetture > 1
        ? ` (${numeroLetture} letture validate in un'unica azione)`
        : '';
    const suffissoModifica = eraGiaValidato ? ' (aggiornato)' : '';

    showToast('success', 'Validazione salvata', messaggioBase + suffissoEpisodio + suffissoModifica);

    // Se eravamo in modalità storico → ricarica la lista storico
    if (validazioneCorrente?.modalita === 'storico') {
        const sel = document.getElementById('storico-select');
        if (sel?.value) {
            const resFresco = await fetch(`${API}/pazienti/by-codice/${sel.value}/episodi`);
            if (resFresco?.ok) {
                const aggiornati = await resFresco.json();
                renderStoricoEpisodi(aggiornati, sel.value);
            }
        }
    }

    // Ricarica sempre la tabella anomalie da validare
    await caricaEpisodi();
}

// Chiudi modal cliccando overlay
document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
    if (e.target === document.getElementById('modal-overlay')) chiudiModal();
});
document.getElementById('modal-paziente-overlay')?.addEventListener('click', (e) => {
    if (e.target === document.getElementById('modal-paziente-overlay')) chiudiModalPaziente();
});

// ============================================================
// BOTTONE REFRESH ANOMALIE
// ============================================================

document.getElementById('btn-refresh-anomalie')?.addEventListener('click', caricaEpisodi);

// ============================================================
// HELPER — formattazione timestamp
// ============================================================

function formatTs(ts) {
    if (!ts) return '—';
    try {
        const d = new Date(ts);
        return d.toLocaleString('it-IT', {
            day:    '2-digit',
            month:  '2-digit',
            hour:   '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch {
        return ts;
    }
}

// ============================================================
// HELPER — render pill temperatura
// ============================================================

function renderTempPill(label) {
    const map = {
        ipotermia:   'pill-amber',
        normale:     'pill-teal',
        febbre:      'pill-amber',
        febbre_alta: 'pill-red',
        sconosciuta: 'pill-muted'
    };
    const cls = map[label] || 'pill-muted';
    return `<span class="pill ${cls}">${label || '—'}</span>`;
}

// ============================================================
// HELPER — render esito medico
// ============================================================

function renderEsito(esito) {
    if (!esito) return '<span class="pill pill-muted">in attesa</span>';
    if (esito === 'vero_positivo')
        return '<span class="pill pill-red">✓ vero positivo</span>';
    if (esito === 'falso_allarme')
        return '<span class="pill pill-teal">✓ falso allarme</span>';
    return `<span class="pill pill-muted">${esito}</span>`;
}

// ============================================================
// GRAFICO ECG ESTESO (nel modal di validazione)
// ============================================================

function renderGraficoECGEsteso(data) {
    if (!data.ecg_window_pronta || !data.ecg_window || data.ecg_window.length === 0) {
        return `
            <div style="margin:0.5rem 0 1.25rem;padding:1rem;background:var(--surface2);border-radius:8px;border:1px solid var(--border);text-align:center;">
                <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.6rem;">
                    ⏳ Traccia ECG (30s) in elaborazione — attendo i campioni successivi all'anomalia
                </div>
                <button class="btn btn-ghost" style="font-size:0.72rem" onclick="aggiornaTracciaECG('${data._id}')">Riprova</button>
            </div>
        `;
    }

    const campioni    = data.ecg_window;
    const sampleRate   = data.ecg_window_sample_rate || 250;
    const indiceAnomalia = data.ecg_window_anomalia_index ?? Math.floor(campioni.length / 2);

    const width = 420, height = 150, padding = 18;
    const n = campioni.length;
    const min = Math.min(...campioni, -1);
    const max = Math.max(...campioni, 1);
    const range = (max - min) || 1;

    const x = i => padding + (n <= 1 ? 0 : (i / (n - 1)) * (width - padding * 2));
    const y = v => height - padding - ((v - min) / range) * (height - padding * 2);

    const polyline = campioni.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const xAnomalia = x(Math.min(indiceAnomalia, n - 1));
    const durataSec = Math.round(n / sampleRate);

    return `
        <div style="margin:0.5rem 0 1.25rem;">
            <div style="font-size:0.72rem;font-weight:600;text-transform:uppercase;letter-spacing:0.08em;color:var(--text-muted);margin-bottom:0.5rem;">
                Traccia ECG · ${durataSec}s (prima e dopo l'evento di picco)
            </div>
            <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="width:100%;max-width:${width}px;background:var(--surface2);border-radius:8px;border:1px solid var(--border);display:block;">
                <rect x="${(xAnomalia - 2).toFixed(1)}" y="0" width="4" height="${height}" fill="var(--red)" opacity="0.25" />
                <polyline points="${polyline}" fill="none" stroke="var(--teal)" stroke-width="1.3" />
                <line x1="${xAnomalia.toFixed(1)}" y1="0" x2="${xAnomalia.toFixed(1)}" y2="${height}" stroke="var(--red)" stroke-width="1.5" stroke-dasharray="4,3" />
            </svg>
            <div style="font-size:0.7rem;color:var(--text-muted);margin-top:0.4rem;">
                Linea rossa = istante di score più alto nell'episodio
            </div>
        </div>
    `;
}

async function aggiornaTracciaECG(annotationId) {
    const res = await apiFetch(`/annotazioni/${annotationId}`);
    if (!res || !res.ok) return;
    const fresca = await res.json();

    if (!validazioneCorrente) return;

    const documenti = validazioneCorrente.data.documenti || [];
    const idx = documenti.findIndex(d => d._id === annotationId);
    if (idx !== -1) {
        documenti[idx] = { ...documenti[idx], ...fresca };
    }

    const container = document.getElementById('modal-ecg-esteso');
    if (container) {
        const documentoAggiornato = scegliDocumentoPerGrafico(validazioneCorrente.data);
        container.outerHTML = `<div id="modal-ecg-esteso">${renderGraficoECGEsteso(documentoAggiornato)}</div>`;
    }
}

// ============================================================
// INIT — avvio applicazione
// ============================================================

async function init() {
    await caricaProfiloMedico();
    await caricaEpisodi();
    await caricaPazienti();   // già così — ok, è awaited

    aggiornaBottoneNotifiche();
    connettiBroker();

    setInterval(caricaEpisodi, 8000);
    setInterval(caricaPazienti, 30000);
}

init();