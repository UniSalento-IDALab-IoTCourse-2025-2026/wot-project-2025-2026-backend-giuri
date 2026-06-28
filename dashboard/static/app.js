// ============================================================
// CardioSense — app.js
// Dashboard medico: MQTT WebSocket + polling REST ibrido
// ============================================================

const API    = 'http://localhost:8000';
const BROKER = 'ws://localhost:9001';   // WebSocket Mosquitto
const TOPIC_ALLARMI = 'cardiosense/allarmi';

// ============================================================
// STATO GLOBALE
// ============================================================

let token        = localStorage.getItem('cs_token');
let medicoNome   = '';
let pazienti     = [];          // cache lista pazienti
let anomalie     = [];          // cache anomalie non validate
let validazioneCorrente = null; // { id, data } per il modal

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
        storico:    'Storico annotazioni'
    };
    document.getElementById('topbar-title').textContent = titoli[sezione] || sezione;

    // Carica dati contestuali
    if (sezione === 'anomalie')  caricaAnomalie();
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
    // Non esiste un endpoint /me dedicato — usiamo il token JWT decodificato
    // oppure carichiamo la lista pazienti (che richiede auth) per verificare
    // e ricaviamo il nome dal token
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        const email = payload.sub || '';
        medicoNome = email.split('@')[0];

        // Capitalizza prima lettera
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
            'Riceverai una notifica per ogni nuova anomalia ECG rilevata.'
        );
    } else if (Notification.permission === 'denied') {
        notificheAbilitate = false;
        aggiornaBottoneNotifiche();
        showToast('alarm', 'Permesso negato',
            'Clicca sull\'icona del lucchetto nella barra degli indirizzi → Notifiche → Consenti, poi ricarica la pagina');
    }
}

function mostraNotificaSistema(titolo, corpo) {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    if (!notificheAbilitate) return;   // rispetta il toggle lato JS

    try {
        const notif = new Notification(titolo, {
            body: corpo,
            tag: 'cardiosense-' + Date.now(),   // tag univoco: ogni allarme genera una notifica propria
            requireInteraction: true             // resta visibile finché il medico non la chiude
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
    suonaAllarme();

    const ts = msg.timestamp
        ? new Date(msg.timestamp).toLocaleTimeString('it-IT')
        : 'adesso';

    showToast(
        'alarm',
        `⚠ Anomalia ECG — Paziente ${msg.paziente_id}`,
        `Score: ${(msg.ecg_score * 100).toFixed(0)}% · Temp: ${msg.temperatura_label} · ${ts}`
    );

    mostraNotificaSistema(
        `⚠ Anomalia ECG — Paziente ${msg.paziente_id}`,
        `Score: ${(msg.ecg_score * 100).toFixed(0)}% · Temp: ${msg.temperatura_label} · ${ts}`
    );

    // Aggiorna KPI ultimo allarme
    document.getElementById('kpi-ultimo').textContent = ts;
    document.getElementById('kpi-ultimo-meta').textContent =
        `Paziente ${msg.paziente_id}`;

    // Aggiorna badge sidebar
    aggiornaContatoreBadge(1);

    // Aggiorna KPI anomalie
    const kpiEl = document.getElementById('kpi-anomalie');
    const corrente = parseInt(kpiEl.textContent) || 0;
    kpiEl.textContent = corrente + 1;

    // Se siamo già sulla sezione anomalie → ricarica
    const sezioneAttiva = document.querySelector('.section.active')?.id;
    if (sezioneAttiva === 'section-anomalie' || sezioneAttiva === 'section-panoramica') {
        setTimeout(caricaAnomalie, 800);
    }
}

// ============================================================
// POLLING REST — anomalie ogni 8 secondi
// ============================================================

async function caricaAnomalie() {
    const res = await apiFetch('/anomalie');
    if (!res || !res.ok) return;

    anomalie = await res.json();

    const count = anomalie.length;
    document.getElementById('kpi-anomalie').textContent = count;
    aggiornaContatoreBadge(count, true);

    renderTabellaAnomalieCompatta(anomalie.slice(0, 5));   // panoramica (max 5)
    renderTabellaAnomalie(anomalie);                        // sezione completa
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

function labelPaziente(a) {
    if (a.paziente_nome && a.paziente_cognome) {
        return `${a.paziente_nome} ${a.paziente_cognome}
            <span style="display:block;font-family:var(--mono);font-size:0.7rem;color:var(--text-muted)">${a.paziente_id}</span>`;
    }
    return `<span style="font-family:var(--mono);font-size:0.8rem">${a.paziente_id}</span>`;
}

// ============================================================
// RENDER — tabella anomalie (panoramica, max 5)
// ============================================================

function renderTabellaAnomalieCompatta(lista) {
    const tbody = document.getElementById('panoramica-tbody');
    if (!tbody) return;

    if (lista.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6">
            <div class="empty-state"><div class="empty-icon">◎</div>Nessuna anomalia in attesa</div>
        </td></tr>`;
        return;
    }

    tbody.innerHTML = lista.map(a => `
        <tr>
            <td>${labelPaziente(a)}</td>
            <td><span class="pill pill-red">anomalo</span></td>
            <td><span class="pill pill-muted">${a.postura_label || '—'}</span></td>
            <td>${renderTempPill(a.temperatura_label)}</td>
            <td style="font-size:0.75rem;color:var(--text-muted);font-family:var(--mono)">${formatTs(a.timestamp)}</td>
            <td>
                <button class="btn btn-teal" style="font-size:0.72rem;padding:0.3rem 0.7rem"
                    onclick="apriModal('${a._id}', ${JSON.stringify(a).replace(/"/g, '&quot;')})">
                    Valida
                </button>
            </td>
        </tr>
    `).join('');
}

// ============================================================
// RENDER — tabella anomalie (sezione completa)
// ============================================================

function renderTabellaAnomalie(lista) {
    const tbody = document.getElementById('anomalie-tbody');
    if (!tbody) return;

    if (lista.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6">
            <div class="empty-state"><div class="empty-icon">✓</div>Nessuna anomalia in attesa</div>
        </td></tr>`;
        return;
    }

    tbody.innerHTML = lista.map(a => `
        <tr>
            <td>${labelPaziente(a)}</td>
            <td>
                <div style="display:flex;align-items:center;gap:0.5rem">
                    <span class="pill pill-red">anomalo</span>
                    <span style="font-family:var(--mono);font-size:0.72rem;color:var(--text-muted)">${(a.ecg_score * 100).toFixed(0)}%</span>
                </div>
            </td>
            <td><span class="pill pill-muted">${a.postura_label || '—'}</span></td>
            <td>${renderTempPill(a.temperatura_label)}</td>
            <td style="font-size:0.75rem;color:var(--text-muted);font-family:var(--mono)">${formatTs(a.timestamp)}</td>
            <td>
                <button class="btn btn-teal" style="font-size:0.72rem;padding:0.3rem 0.7rem"
                    onclick="apriModal('${a._id}', ${JSON.stringify(a).replace(/"/g, '&quot;')})">
                    Valida
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

    // Mostra codice generato
    document.getElementById('codice-generato').style.display = 'block';
    document.getElementById('codice-value').textContent = paziente.codice_accesso;
    document.getElementById('btn-crea-paziente').style.display = 'none';

    showToast('success', 'Paziente creato', `${paziente.nome} ${paziente.cognome} — codice: ${paziente.codice_accesso}`);

    // Ricarica lista
    await caricaPazienti();
}

// ============================================================
// STORICO
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

    const res = await apiFetch(`/pazienti/${pazienteId}/storico?limit=100`);
    if (!res || !res.ok) return;

    const storico = await res.json();
    renderTabellaStorico(storico);
});

function renderTabellaStorico(lista) {
    const tbody = document.getElementById('storico-tbody');
    if (!tbody) return;

    if (lista.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6">
            <div class="empty-state"><div class="empty-icon">▤</div>Nessuna annotazione trovata</div>
        </td></tr>`;
        return;
    }

    tbody.innerHTML = lista.map(a => `
        <tr>
            <td style="font-size:0.75rem;font-family:var(--mono);color:var(--text-muted)">${formatTs(a.timestamp)}</td>
            <td>${a.ecg_label === 'anomalo'
                ? '<span class="pill pill-red">anomalo</span>'
                : '<span class="pill pill-teal">normale</span>'}</td>
            <td style="font-family:var(--mono);font-size:0.78rem">${(a.ecg_score * 100).toFixed(0)}%</td>
            <td><span class="pill pill-muted" style="font-size:0.7rem">${a.postura_label || '—'}</span></td>
            <td>${renderTempPill(a.temperatura_label)}</td>
            <td>${renderEsito(a.esito_medico)}</td>
        </tr>
    `).join('');
}

// ============================================================
// MODAL — validazione anomalia
// ============================================================

let esitoSelezionato = null;

function apriModal(annotationId, data) {
    validazioneCorrente = { id: annotationId, data };
    esitoSelezionato = null;

    // Intestazione modal: mostra nome/cognome se disponibili
    const intestazione = (data.paziente_nome && data.paziente_cognome)
        ? `${data.paziente_nome} ${data.paziente_cognome} (${data.paziente_id})`
        : data.paziente_id;
    document.getElementById('modal-paziente-info').textContent = `Paziente: ${intestazione}`;

    document.getElementById('modal-details').innerHTML = `
        <div id="modal-ecg-esteso">${renderGraficoECGEsteso(data)}</div>
        <div class="modal-info-row">
            <span class="modal-info-key">ECG Score</span>
            <span class="pill pill-red">${(data.ecg_score * 100).toFixed(1)}%</span>
        </div>
        <div class="modal-info-row">
            <span class="modal-info-key">Postura</span>
            <span>${data.postura_label || '—'}</span>
        </div>
        <div class="modal-info-row">
            <span class="modal-info-key">Temperatura</span>
            <span>${data.temperatura_valore}°C — ${data.temperatura_label}</span>
        </div>
        <div class="modal-info-row">
            <span class="modal-info-key">Timestamp</span>
            <span style="font-family:var(--mono);font-size:0.78rem">${formatTs(data.timestamp)}</span>
        </div>
    `;

    // Reset selezione esito
    document.getElementById('btn-vp').className = 'esito-btn';
    document.getElementById('btn-fa').className = 'esito-btn';
    document.getElementById('modal-note').value = '';

    document.getElementById('modal-overlay').classList.add('open');
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
    btn.textContent = 'Salvataggio...';
    btn.disabled = true;

    const res = await apiFetch(`/anomalie/${validazioneCorrente.id}/valida`, {
        method: 'PATCH',
        body: JSON.stringify({ esito: esitoSelezionato, note })
    });

    btn.textContent = 'Conferma validazione';
    btn.disabled = false;

    if (!res || !res.ok) {
        showToast('alarm', 'Errore', 'Impossibile salvare la validazione');
        return;
    }

    chiudiModal();

    kpiValidateOggi++;
    document.getElementById('kpi-validate').textContent = kpiValidateOggi;

    showToast('success', 'Validazione salvata',
        esitoSelezionato === 'vero_positivo'
            ? 'Anomalia confermata — dati inviati al ri-addestramento'
            : 'Falso allarme registrato');

    // Ricarica tabelle
    await caricaAnomalie();
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

document.getElementById('btn-refresh-anomalie')?.addEventListener('click', caricaAnomalie);

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

// dashboard/static/app.js — aggiungere queste due funzioni

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
                Traccia ECG · ${durataSec}s (prima e dopo l'evento)
            </div>
            <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="width:100%;max-width:${width}px;background:var(--surface2);border-radius:8px;border:1px solid var(--border);display:block;">
                <rect x="${(xAnomalia - 2).toFixed(1)}" y="0" width="4" height="${height}" fill="var(--red)" opacity="0.25" />
                <polyline points="${polyline}" fill="none" stroke="var(--teal)" stroke-width="1.3" />
                <line x1="${xAnomalia.toFixed(1)}" y1="0" x2="${xAnomalia.toFixed(1)}" y2="${height}" stroke="var(--red)" stroke-width="1.5" stroke-dasharray="4,3" />
            </svg>
            <div style="font-size:0.7rem;color:var(--text-muted);margin-top:0.4rem;">
                Linea rossa = istante della classificazione anomala
            </div>
        </div>
    `;
}

async function aggiornaTracciaECG(annotationId) {
    const res = await apiFetch(`/annotazioni/${annotationId}`);
    if (!res || !res.ok) return;
    const fresca = await res.json();

    if (!validazioneCorrente || validazioneCorrente.id !== annotationId) return;
    validazioneCorrente.data = { ...validazioneCorrente.data, ...fresca };

    const container = document.getElementById('modal-ecg-esteso');
    if (container) {
        container.outerHTML = `<div id="modal-ecg-esteso">${renderGraficoECGEsteso(validazioneCorrente.data)}</div>`;
    }
}

// ============================================================
// INIT — avvio applicazione
// ============================================================

async function init() {
    await caricaProfiloMedico();
    await caricaAnomalie();
    await caricaPazienti();

    aggiornaBottoneNotifiche();

    connettiBroker();

    // Polling REST ogni 8 secondi per anomalie nuove
    setInterval(caricaAnomalie, 8000);

    // Polling pazienti ogni 30 secondi (cambiano raramente)
    setInterval(caricaPazienti, 30000);
}

init();