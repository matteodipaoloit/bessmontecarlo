import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
from datetime import datetime

st.set_page_config(page_title="HPC Station - BESS & Satellites Risk Assessment Tool", layout="wide", page_icon="⚡")

st.markdown("""
<style>
.main-title{font-size:2rem;font-weight:700;color:#1a73e8;}
.subtitle{font-size:1rem;color:#666;margin-bottom:1.5rem;}
.metric-card{background:#f0f7ff;border-left:4px solid #1a73e8;padding:1rem;border-radius:8px;margin:0.3rem 0;}
.risk-low{background:#e8f5e9;border-left:4px solid #43a047;}
.risk-mid{background:#fff8e1;border-left:4px solid #fb8c00;}
.risk-high{background:#ffebee;border-left:4px solid #e53935;}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">⚡ HPC Station — BESS & Satellites Risk Assessment Tool</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Simulazione Montecarlo — slot 5 min — 1 auto per stallo — coda gestita</div>', unsafe_allow_html=True)

# ─── COSTANTI FISSE ──────────────────────────────────────────────────────────
SLOT_MIN = 5
SLOT_H   = SLOT_MIN / 60.0

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Parametri Impianto")

    # ══════════════════════════════════════════════════════
    # SEZIONE A — PARAMETRI FISICI (non cambiano le giornate)
    # ══════════════════════════════════════════════════════
    st.markdown("""
    <div style="background:#e8f0fe;border-left:4px solid #1a73e8;
                padding:6px 10px;border-radius:4px;margin-bottom:8px">
    <b style="color:#0d47a1">🔵 PARAMETRI FISICI</b><br>
    <span style="font-size:0.8rem;color:#555">Non cambiano le giornate simulate — confronti diretti tra run</span>
    </div>""", unsafe_allow_html=True)

    st.subheader("🕐 Orario Operativo")
    col_h1, col_h2 = st.columns(2)
    with col_h1:
        ORA_INIZIO = st.number_input("Ora apertura", min_value=0, max_value=23, value=0, step=1)
    with col_h2:
        ORA_FINE   = st.number_input("Ora chiusura", min_value=1, max_value=24, value=24, step=1)

    if ORA_FINE <= ORA_INIZIO:
        st.error("⚠️ L'ora di chiusura deve essere maggiore dell'ora di apertura.")
        ORA_FINE = ORA_INIZIO + 1

    ore_operative = ORA_FINE - ORA_INIZIO
    N_SLOT     = int(ore_operative * 60 / SLOT_MIN)
    SLOT_TIMES = []
    for i in range(N_SLOT):
        minuti_totali = ORA_INIZIO * 60 + i * SLOT_MIN
        SLOT_TIMES.append(f"{minuti_totali // 60:02d}:{minuti_totali % 60:02d}")

    st.caption(f"Ore operative: **{ore_operative}h** ({N_SLOT} slot da 5 min)")

    st.subheader("🔌 Rete & Stalli")
    potenza_rete_kw      = st.number_input("Potenza dalla rete (kW) — limite fisso", 0.0, 10000.0, 100.0, 10.0)
    num_pdr              = st.number_input("Numero stalli (PDR)", 1, 100, 4)
    potenza_max_stallo   = st.number_input("Potenza massima per stallo (kW)", 10.0, 1000.0, 600.0, 10.0,
                                           help="Limite fisso del singolo stallo. Se più stalli attivi, la potenza disponibile si divide tra loro.")
    ricariche_per_pdr    = st.number_input("Ricariche giornaliere per stallo", 1, 50, 6)
    kwh_medi_ricarica    = st.number_input("kWh medi per ricarica", 1.0, 500.0, 31.06, 0.01)

    with st.expander("⚡ Power Unit", expanded=False):
        num_pu           = st.number_input("Numero Power Unit", 1, 50, 1,
                                           help="Numero totale di Power Unit nella stazione.")
        pdr_per_pu       = st.number_input("PDR per Power Unit", 1, 100, 8,
                                           help="Numero di stalli collegati a ogni Power Unit.")
        potenza_pu_kw    = st.number_input("Potenza massima per Power Unit (kW)", 10.0, 5000.0, 600.0, 10.0,
                                           help="Limite aggregato di ogni PU. Se più PDR attivi sulla stessa PU, la potenza si divide tra loro.")
        st.caption(f"Potenza max per PDR (tutti attivi sulla stessa PU): {potenza_pu_kw/pdr_per_pu:.0f} kW")
        if num_pu * pdr_per_pu < num_pdr:
            st.warning(f"⚠️ N_pu ({int(num_pu)}) × PDR/PU ({int(pdr_per_pu)}) = {int(num_pu*pdr_per_pu)} < N_pdr ({int(num_pdr)}): "
                       f"alcuni stalli non appartengono a nessuna PU. Aumentare N_pu o PDR/PU.")

    st.subheader("🔋 Batteria (BESS)")
    potenza_carica_kw    = st.number_input("Potenza di carica batteria (kW)",  1.0, 5000.0, 108.0, 1.0)
    potenza_scarica_kw   = st.number_input("Potenza di scarica batteria (kW)", 1.0, 5000.0, 108.0, 1.0)
    capacita_singola_kwh = st.number_input("Capacità singola batteria (kWh)",  1.0, 2000.0, 215.0, 1.0)
    num_batterie         = st.number_input("Numero batterie", 0, 20, 2)

    st.subheader("📏 Soglie Congestione")
    kw_soglia_sistema = st.number_input(
        "Soglia potenza per stallo (kW)", 1.0, 500.0, 100.0, 1.0,
        help="Tipo A: episodio se kW_assegnato < min(kW_max, kWh/dt) E kW_max×coeff > S_auto E kW_max×coeff > S_sis."
    )
    kw_soglia_auto = st.number_input(
        "Soglia potenza auto (kW)", 1.0, 500.0, 150.0, 1.0,
        help="L'auto è considerata 'veloce' quando kw_max_auto × coeff_picco supera questa soglia."
    )
    coeff_picco_pct = st.slider(
        "Coefficiente picco potenza auto (%)", 100, 200, 145, 5,
        help="Moltiplica kw_max_auto per il check congestione."
    )
    coeff_picco = coeff_picco_pct / 100.0
    kw_soglia_potenza = kw_soglia_sistema

    st.subheader("🎲 Simulazione")
    n_sim    = st.selectbox("Simulazioni Montecarlo", [500, 1000, 2000, 5000], index=1)
    n_warmup = st.selectbox("Simulazioni warm-up (stima SOC iniziale)", [50, 100, 200, 500], index=2,
                             help="Giornate simulate per stimare il SOC realistico a inizio giornata.")
    soc_min_pct = st.slider("Soglia 'batteria scarica' (%)", 0, 50, 10)

    # Calcola SOC iniziale teorico
    ore_pre_prev      = ORA_INIZIO
    ore_post_prev     = 24 - ORA_FINE
    P_carica_tot_prev = min(potenza_rete_kw, potenza_carica_kw * num_batterie)
    kwh_ricaricabili  = (ore_pre_prev + ore_post_prev) * P_carica_tot_prev
    cap_teorica       = capacita_singola_kwh * num_batterie
    soc_start_teorico = min(100.0, kwh_ricaricabili / cap_teorica * 100) if cap_teorica > 0 else 100.0
    st.info(
        f"🔋 SOC a inizio giornata (stimato worst-case): **{soc_start_teorico:.1f}%**\n\n"
        f"Ricarica: {ore_post_prev}h post ({ORA_FINE}:00→24:00) + "
        f"{ore_pre_prev}h pre (0:00→{ORA_INIZIO}:00) = "
        f"{ore_pre_prev + ore_post_prev}h × {P_carica_tot_prev:.0f} kW = "
        f"{kwh_ricaricabili:.0f} kWh su {cap_teorica:.0f} kWh. "
        f"Il valore reale viene stimato dal warm-up prima della simulazione."
    )

    st.divider()

    # ══════════════════════════════════════════════════════
    # SEZIONE B — PARAMETRI STOCASTICI (rigenerano le giornate)
    # ══════════════════════════════════════════════════════
    st.markdown("""
    <div style="background:#fce8e6;border-left:4px solid #e53935;
                padding:6px 10px;border-radius:4px;margin-bottom:8px">
    <b style="color:#b71c1c">🔴 PARAMETRI STOCASTICI</b><br>
    <span style="font-size:0.8rem;color:#555">Cambiano la natura delle giornate simulate — i run non sono più confrontabili tra loro</span>
    </div>""", unsafe_allow_html=True)

    with st.expander("⚙️ Variabilità energia per ricarica", expanded=False):
        sigma_pct = st.slider(
            "Variabilità σ (% della media)",
            min_value=0, max_value=100, value=56, step=1,
            help="Deviazione standard come % di E_avg.")
        clip_min_pct = st.slider(
            "Limite inferiore (% della media)",
            min_value=1, max_value=80, value=4, step=1,
            help="Energia minima che un'auto può richiedere.")
        clip_max_pct = st.slider(
            "Limite superiore (% della media)",
            min_value=110, max_value=500, value=300, step=5,
            help="Energia massima che un'auto può richiedere.")
        if clip_min_pct >= clip_max_pct - 10:
            st.warning("⚠️ Il limite inferiore deve essere significativamente minore del superiore.")
        st.caption(
            f"Con E_avg = {kwh_medi_ricarica:.0f} kWh: "
            f"σ = {kwh_medi_ricarica * sigma_pct / 100:.1f} kWh, "
            f"range [{kwh_medi_ricarica * clip_min_pct / 100:.1f} – "
            f"{kwh_medi_ricarica * clip_max_pct / 100:.1f}] kWh"
        )

    with st.expander("🚗 Velocità di ricarica auto", expanded=False):
        kw_auto_media = st.number_input(
            "Potenza max media delle auto (kW)", 1.0, 500.0, 78.2, 0.1,
            help="Velocità di ricarica massima accettata dall'auto in media.")
        kw_auto_sigma_pct = st.slider(
            "Variabilità σ (% della media)", 0, 100, 49, 1,
            help="Dispersione intorno alla media.")
        kw_auto_min = st.number_input(
            "Minimo (kW)", 1.0, 500.0, 3.5, 0.1,
            help="Potenza minima accettata dall'auto.")
        kw_auto_max = st.number_input(
            "Massimo (kW)", 1.0, 1000.0, 300.6, 0.1,
            help="Potenza massima accettata dall'auto.")
        kw_auto_sigma = kw_auto_media * kw_auto_sigma_pct / 100
        st.caption(
            f"Distribuzione: Normal({kw_auto_media:.0f}, {kw_auto_sigma:.0f}) "
            f"clip [{kw_auto_min:.0f} – {kw_auto_max:.0f}] kW"
        )

    st.subheader("📊 Distribuzione Arrivi")
    distribuzione = st.selectbox("Tipo distribuzione",
                                 ["Doppia Gaussiana (mattina + sera)", "Singola Gaussiana (picco unico)"], index=0)

    p1_default = 12
    p2_default = 16
    pm_default = max(ORA_INIZIO, min(ORA_FINE - 1, 15))

    if distribuzione == "Doppia Gaussiana (mattina + sera)":
        c1, c2 = st.columns(2)
        with c1:
            picco1 = st.slider("Picco mattina (h)", ORA_INIZIO, ORA_FINE - 1, p1_default)
            sigma1 = st.slider("Ampiezza mat. (h)", 0.5, 8.0, 3.5, 0.5)
            peso1  = st.slider("% mattina", 10, 90, 35)
        with c2:
            picco2 = st.slider("Picco sera (h)", ORA_INIZIO, ORA_FINE - 1, p2_default)
            sigma2 = st.slider("Ampiezza sera (h)", 0.5, 8.0, 4.5, 0.5)
            st.metric("% sera", 100 - peso1)
        peso2 = 100 - peso1
    else:
        picco1 = st.slider("Ora picco", ORA_INIZIO, ORA_FINE - 1, pm_default)
        sigma1 = st.slider("Ampiezza (h)", 0.5, 4.0, 2.5, 0.5)
        picco2, sigma2, peso1, peso2 = 0, 1, 100, 0

    st.subheader("🚗 Tempi operativi")
    cooldown_min = st.number_input("Tempo tra ricariche sullo stesso stallo (min)",
                                   min_value=0, max_value=60, value=5, step=5,
                                   help="Minuti di attesa dopo ogni ricarica.")
    cooldown_slot = int(round(cooldown_min / SLOT_MIN)) if cooldown_min > 0 else 0

    with st.expander("🔢 Variabilità numero ricariche giornaliere", expanded=False):
        sigma_ric_pct = st.slider(
            "Variabilità σ (% della media)", 0, 100, 0, 1,
            help="0% = numero fisso (comportamento originale). "
                 "Es. 20% con media 24 sessioni → σ = 4.8 sessioni/giorno.")
        clip_ric_min = st.slider(
            "Limite inferiore (% della media)", 1, 99, 50, 1,
            help="Numero minimo di sessioni come % della media.")
        clip_ric_max = st.slider(
            "Limite superiore (% della media)", 101, 300, 150, 1,
            help="Numero massimo di sessioni come % della media.")
        ric_media = int(num_pdr * ricariche_per_pdr)
        ric_min   = max(1, int(ric_media * clip_ric_min / 100))
        ric_max   = int(ric_media * clip_ric_max / 100)
        st.caption(
            f"Media: {ric_media} sessioni/giorno | "
            f"σ = {ric_media * sigma_ric_pct / 100:.1f} | "
            f"range [{ric_min} – {ric_max}]"
        )

    st.divider()
    run_btn = st.button("▶ AVVIA SIMULAZIONE", type="primary", use_container_width=True)


# ─── FUNZIONI ────────────────────────────────────────────────────────────────

def build_weights():
    slot_ore = np.array([ORA_INIZIO + i * SLOT_H for i in range(N_SLOT)])
    if distribuzione == "Singola Gaussiana (picco unico)":
        w = np.exp(-0.5 * ((slot_ore - picco1) / sigma1) ** 2)
    else:
        g1 = (peso1 / 100) * np.exp(-0.5 * ((slot_ore - picco1) / sigma1) ** 2)
        g2 = (peso2 / 100) * np.exp(-0.5 * ((slot_ore - picco2) / sigma2) ** 2)
        w  = g1 + g2
    return w / w.sum()

def _stats_delta(lst):
    """Calcola media, mediana, min, max di una lista di delta. Restituisce dict con None se vuota."""
    if not lst:
        return {"media": None, "mediana": None, "min": None, "max": None, "n": 0}
    a = np.array(lst)
    return {
        "media":   float(np.mean(a)),
        "mediana": float(np.median(a)),
        "min":     float(np.min(a)),
        "max":     float(np.max(a)),
        "n":       len(a),
    }

def run_montecarlo():
    np.random.seed(42)
    cap_totale    = capacita_singola_kwh * num_batterie
    soc_soglia    = cap_totale * soc_min_pct / 100.0
    weights       = build_weights()
    ricariche_mu  = int(num_pdr * ricariche_per_pdr)
    ricariche_max = max(1, int(ricariche_mu * clip_ric_max / 100))  # dimensione pre-gen
    ricariche_tot = ricariche_mu  # default per warm-up

    # Potenze totali del sistema batteria
    P_carica_tot  = min(potenza_rete_kw, potenza_carica_kw * num_batterie)
    P_scarica_tot = potenza_scarica_kw * num_batterie

    # Ore di ricarica notturna (due spezzoni separati)
    ore_pre  = ORA_INIZIO       # 0:00 → ORA_INIZIO
    ore_post = 24 - ORA_FINE    # ORA_FINE → 24:00

    # ── Pre-genera i numeri casuali per tutte le n_sim simulazioni reali ─────
    # Fatto PRIMA del warm-up: così il warm-up non sfasa la sequenza
    # e confronti tra run con parametri diversi usano le stesse giornate
    rng_sim = np.random.default_rng(42)
    # Pre-genera N_tot per giornata (variabilità ricariche)
    if sigma_ric_pct > 0:
        pre_ntot = np.clip(
            rng_sim.normal(ricariche_mu, ricariche_mu * sigma_ric_pct / 100, size=n_sim),
            ric_min, ric_max).astype(int)
    else:
        pre_ntot = np.full(n_sim, ricariche_mu, dtype=int)
    pre_slot   = [rng_sim.choice(N_SLOT, size=ricariche_max, p=weights)   for _ in range(n_sim)]
    pre_kwh    = [np.clip(
                    rng_sim.normal(kwh_medi_ricarica, kwh_medi_ricarica * sigma_pct / 100, size=ricariche_max),
                    kwh_medi_ricarica * clip_min_pct / 100,
                    kwh_medi_ricarica * clip_max_pct / 100)
                  for _ in range(n_sim)]
    pre_kwmax  = [np.clip(
                    rng_sim.normal(kw_auto_media, kw_auto_sigma, size=ricariche_max),
                    kw_auto_min, kw_auto_max)
                  for _ in range(n_sim)]

    # ── Funzione interna: simula una singola giornata ─────────────────────────
    def simula_giornata(soc_inizio, registra=False, idx=0):
        """
        Simula una giornata operativa partendo da soc_inizio.
        Se registra=True usa i numeri casuali pre-generati (idx = indice simulazione),
        così il warm-up non influenza la sequenza delle simulazioni reali.
        """
        soc     = soc_inizio
        soc_min = soc_inizio

        if registra:
            n_ric           = int(pre_ntot[idx])
            slot_arrivo     = pre_slot[idx][:n_ric]
            kwh_target      = pre_kwh[idx][:n_ric].copy()
            kw_max_per_auto = pre_kwmax[idx][:n_ric].copy()
        else:
            n_ric = ricariche_mu
            slot_arrivo = np.random.choice(N_SLOT, size=n_ric, p=weights)
            kwh_target  = np.random.normal(kwh_medi_ricarica, kwh_medi_ricarica * sigma_pct / 100, size=n_ric)
            kwh_target  = np.clip(kwh_target,
                                  kwh_medi_ricarica * clip_min_pct / 100,
                                  kwh_medi_ricarica * clip_max_pct / 100)
            kw_max_per_auto = np.random.normal(kw_auto_media, kw_auto_sigma, size=n_ric)
            kw_max_per_auto = np.clip(kw_max_per_auto, kw_auto_min, kw_auto_max)

        coda   = []  # ogni elemento: (kwh_residui, kw_max_auto)
        # Assegna ogni stallo alla sua PU (0-indexed)
        stalli = [{'kwh': 0.0, 'cooldown': 0, 'kw_max': 0.0,
                   'pu': i // int(pdr_per_pu)} for i in range(int(num_pdr))]
        arrivi_per_slot = {t: [] for t in range(N_SLOT)}
        for i in range(n_ric):
            arrivi_per_slot[slot_arrivo[i]].append((kwh_target[i], kw_max_per_auto[i]))

        en_mancante     = 0.0
        n_slot_stress   = 0
        slot_occupati   = 0
        kwh_erogati_tot = 0.0
        n_episodi_bassa  = 0   # episodi (transizioni ok→bassa) per stallo
        giorno_ha_bassa  = False
        stallo_in_bassa  = [False] * int(num_pdr)  # traccia se stallo già in bassa pot.
        slot_batt_attiva = 0   # slot con auto e kw_batt_disp > 0
        slot_batt_soglia = 0   # slot con auto e soc <= soc_soglia (batt bloccata)
        slot_con_auto    = 0   # slot con almeno 1 auto attiva
        # Debug PU: slot-stallo in cui il vincolo PU è più stringente del vincolo globale
        slot_pu_binding  = 0
        # Debug stallo: slot-stallo in cui il vincolo P_stallo è più stringente di tutto il resto
        slot_stallo_binding = 0
        # Distribuzione stalli attivi per slot: contatori 0,1,2,3,4,5+(>4)
        dist_attivi = [0, 0, 0, 0, 0, 0]  # indici 0..4 = esatti, 5 = >=5
        delta_richiesto_list = []   # kw_richiesto_i - kw_per_stallo_disp al momento episodio Tipo A
        delta_kwmax_list     = []   # kw_max_auto_i  - kw_per_stallo_disp al momento episodio Tipo A
        # Tipo B: sistema non soddisfa qualsiasi auto (soglia = P_stallo)
        n_episodi_b   = 0
        giorno_ha_b   = False
        stallo_in_b   = [False] * int(num_pdr)
        delta_b_list  = []   # kw_richiesto_i - kw_per_stallo_disp al momento episodio Tipo B
        # Slot extra: kWh deficit accumulati per sessione (indice = i_st)
        kwh_def3 = [0.0] * int(num_pdr)   # deficit con coeff (Opzione 3)
        kwh_def4 = [0.0] * int(num_pdr)   # deficit nudo (Opzione 4)
        slot_extra3_list = []   # slot_extra per sessione completata, Opz.3
        slot_extra4_list = []   # slot_extra per sessione completata, Opz.4

        for t in range(N_SLOT):
            # Cooldown
            for st_ in stalli:
                if st_['kwh'] <= 0.0 and st_['cooldown'] > 0:
                    st_['cooldown'] -= 1

            # Arrivi e assegnazione stalli
            for item in arrivi_per_slot[t]:
                coda.append(item)
            for st_ in stalli:
                if st_['kwh'] <= 0.0 and st_['cooldown'] == 0 and coda:
                    if True:  # nessun limite giornaliero sul totale erogato
                        kwh_s, kw_max_s = coda.pop(0)
                        st_['kwh']    = kwh_s
                        st_['kw_max'] = kw_max_s
                        idx_s = stalli.index(st_)
                        kwh_def3[idx_s] = 0.0
                        kwh_def4[idx_s] = 0.0
                    else:
                        break

            n_attivi = sum(1 for st_ in stalli if st_['kwh'] > 0.0)
            slot_occupati += n_attivi  # ogni stallo attivo in questo slot conta 1
            dist_attivi[min(n_attivi, 5)] += 1

            if registra:
                coda_matrix[idx, t]     = len(coda)
                n_attivi_matrix[idx, t] = n_attivi

            if n_attivi == 0:
                kw_ric = min(P_carica_tot, potenza_rete_kw, (cap_totale - soc) / SLOT_H)
                soc = min(cap_totale, soc + kw_ric * SLOT_H)
                if registra:
                    soc_matrix[idx, t] = soc
                continue

            # Potenza disponibile
            kw_batt_disp = 0.0
            if soc > soc_soglia:
                kw_batt_disp = min(P_scarica_tot, (soc - soc_soglia) / SLOT_H)

            kw_totale_disp = potenza_rete_kw + kw_batt_disp
            # Debug batteria
            slot_con_auto += 1
            if kw_batt_disp > 0:
                slot_batt_attiva += 1
            elif soc <= soc_soglia and cap_totale > 0:
                slot_batt_soglia += 1

            # Calcola stalli attivi per PU
            attivi_per_pu = {}
            for st_ in stalli:
                if st_['kwh'] > 0.0:
                    attivi_per_pu[st_['pu']] = attivi_per_pu.get(st_['pu'], 0) + 1

            def calcola_kw_assegnati():
                """
                Redistribuisce la potenza disponibile (rete+batt e PU) tra gli stalli attivi.
                Rispetta simultaneamente:
                  - budget globale (rete+batt): somma di tutti gli stalli ≤ kw_totale_disp
                  - budget per PU: somma degli stalli di ogni PU ≤ potenza_pu_kw
                  - domanda individuale: min(limite_stallo, kw_max_auto, kwh/SLOT_H)
                Algoritmo iterativo water-filling: ad ogni iterazione divide i budget residui
                equamente tra i residui non ancora saturi, redistribuisce i surplus.
                """
                # Indici stalli attivi
                idx_attivi = [i for i, st_ in enumerate(stalli) if st_['kwh'] > 0.0]
                if not idx_attivi:
                    return {}

                # Domanda massima per ogni stallo (limite fisico, senza vincoli budget)
                domanda_max = {i: min(potenza_max_stallo,
                                      stalli[i]['kw_max'],
                                      stalli[i]['kwh'] / SLOT_H)
                               for i in idx_attivi}

                assegnati  = {i: 0.0 for i in idx_attivi}
                saturi     = set()  # stalli che hanno raggiunto la loro domanda max

                for _ in range(len(idx_attivi) + 1):  # max iterazioni = n stalli
                    residui = [i for i in idx_attivi if i not in saturi]
                    if not residui:
                        break

                    # Budget globale residuo
                    budget_glob = kw_totale_disp - sum(assegnati.values())

                    # Budget residuo per ogni PU
                    budget_pu = {}
                    for pu in attivi_per_pu:
                        usato_pu = sum(assegnati[i] for i in idx_attivi
                                       if stalli[i]['pu'] == pu)
                        budget_pu[pu] = potenza_pu_kw - usato_pu

                    # Quota globale equa tra i residui
                    residui_per_pu = {}
                    for i in residui:
                        pu = stalli[i]['pu']
                        residui_per_pu[pu] = residui_per_pu.get(pu, 0) + 1

                    n_residui = len(residui)
                    quota_glob = budget_glob / n_residui if n_residui > 0 else 0.0

                    nuovi_saturi = False
                    for i in residui:
                        pu = stalli[i]['pu']
                        quota_pu  = budget_pu[pu] / residui_per_pu[pu]
                        quota_i   = min(quota_glob, quota_pu)
                        fabbisogno = domanda_max[i] - assegnati[i]
                        if fabbisogno <= quota_i + 1e-9:
                            assegnati[i] += fabbisogno
                            saturi.add(i)
                            nuovi_saturi = True
                        # altrimenti lascia la quota all'iterazione successiva

                    if not nuovi_saturi:
                        # Nessun nuovo saturo: assegna le quote finali
                        for i in residui:
                            pu = stalli[i]['pu']
                            quota_pu  = budget_pu[pu] / residui_per_pu[pu]
                            quota_i   = min(quota_glob, quota_pu)
                            assegnati[i] += min(quota_i, domanda_max[i] - assegnati[i])
                        break

                return assegnati, domanda_max

            kw_assegnati, domanda_max_slot = calcola_kw_assegnati()

            # Verifica congestione — usa kW realmente assegnato dal water-fill
            for i_st, st_ in enumerate(stalli):
                attivo = st_['kwh'] > 0.0
                if not attivo:
                    stallo_in_bassa[i_st] = False
                    stallo_in_b[i_st]     = False
                    # Sessione completata: salva slot_extra se > 0
                    if kwh_def3[i_st] > 0 or kwh_def4[i_st] > 0:
                        kw_n = st_['kw_max']
                        if kw_n > 0:
                            slot_extra3_list.append(kwh_def3[i_st] / kw_n / SLOT_H)
                            slot_extra4_list.append(kwh_def4[i_st] / kw_n / SLOT_H)
                        kwh_def3[i_st] = 0.0
                        kwh_def4[i_st] = 0.0
                else:
                    kw_ass       = kw_assegnati.get(i_st, 0.0)   # potenza reale water-fill
                    kw_richiesto = st_['kw_max'] * coeff_picco
                    # domanda senza P_stallo: min(kW_max_auto, kWh_residui/dt)
                    # P_stallo e vincolo del water-fill, non della condizione
                    dom_max_no_stallo = min(st_['kw_max'], st_['kwh'] / SLOT_H)
                    congestionato = kw_ass < dom_max_no_stallo - 1e-6

                    # Tipo A: water-fill ha assegnato meno di domanda_max + filtri soglie
                    if (congestionato
                            and kw_richiesto > kw_soglia_auto
                            and kw_richiesto > kw_soglia_sistema
                            and not stallo_in_bassa[i_st]):
                        n_episodi_bassa += 1
                        giorno_ha_bassa  = True
                        stallo_in_bassa[i_st] = True
                        delta_richiesto_list.append(kw_richiesto - kw_ass)
                        delta_kwmax_list.append(st_['kw_max'] - kw_ass)

                    # Tipo B: water-fill ha assegnato meno di domanda_max (no filtri)
                    if (congestionato
                            and not stallo_in_b[i_st]):
                        n_episodi_b += 1
                        giorno_ha_b  = True
                        stallo_in_b[i_st] = True
                        delta_b_list.append(kw_richiesto - kw_ass)

                    # Slot extra: accumula quando water-fill ha assegnato meno di domanda_max
                    if congestionato:
                        deficit = max(0.0, st_['kw_max'] - kw_ass) * SLOT_H
                        kwh_def3[i_st] += deficit
                        kwh_def4[i_st] += deficit

            # Erogazione effettiva
            kw_domanda = 0.0
            for i_st, st_ in enumerate(stalli):
                if st_['kwh'] > 0.0:
                    kw_limit = kw_assegnati.get(i_st, 0.0)
                    kwh_er = kw_limit * SLOT_H
                    st_['kwh'] -= kwh_er
                    kwh_erogati_tot += kwh_er
                    if st_['kwh'] < 0.01:
                        st_['kwh']      = 0.0
                        st_['cooldown'] = cooldown_slot
                    kw_domanda += kw_limit

                    # Debug vincoli: domanda_raw ricostruita (kwh prima = kwh_dopo + kwh_er)
                    domanda_raw = min(potenza_max_stallo, st_['kw_max'],
                                     (st_['kwh'] + kwh_er) / SLOT_H)
                    if kw_limit < domanda_raw - 1e-6:  # stallo non soddisfatto
                        # Confronta budget effettivi PU vs globale
                        n_att_pu_d = attivi_per_pu.get(st_['pu'], 1)
                        used_altri_glob = sum(kw_assegnati.get(j,0.) for j in kw_assegnati if j!=i_st)
                        used_altri_pu   = sum(kw_assegnati.get(j,0.) for j,s_ in enumerate(stalli)
                                              if s_['kwh']>0. and s_['pu']==st_['pu'] and j!=i_st)
                        quota_glob_eff = (kw_totale_disp - used_altri_glob) / max(1, n_attivi)
                        quota_pu_eff   = (potenza_pu_kw  - used_altri_pu)   / max(1, n_att_pu_d)
                        if quota_pu_eff < quota_glob_eff:
                            slot_pu_binding += 1
                    if kw_limit >= domanda_raw - 1e-6 and domanda_raw >= potenza_max_stallo - 1e-6:
                        slot_stallo_binding += 1

            # kw_per_stallo medio per registrazione
            kw_per_stallo = (kw_domanda / n_attivi) if n_attivi > 0 else 0.0

            # Bilancio rete / batteria
            kw_da_rete = min(kw_domanda, potenza_rete_kw)
            kw_da_batt = min(max(0.0, kw_domanda - kw_da_rete), kw_batt_disp)

            # Energia mancante
            kw_non_cop = max(0.0, kw_domanda - kw_da_rete - kw_da_batt)
            en_mancante += kw_non_cop * SLOT_H

            soc -= kw_da_batt * SLOT_H

            # Ricarica batteria con margine rete residuo
            # La rete può ricaricare la batteria solo se non sta già scaricando
            # e se c'è potenza di rete non usata per gli stalli
            kw_rete_residua = potenza_rete_kw - kw_da_rete
            if kw_da_batt == 0 and kw_rete_residua > 0 and soc < cap_totale:
                soc += min(kw_rete_residua, P_carica_tot, (cap_totale - soc) / SLOT_H) * SLOT_H

            soc = np.clip(soc, 0.0, cap_totale)
            if soc < soc_min:
                soc_min = soc

            if kw_domanda > potenza_rete_kw:
                n_slot_stress += 1

            if registra:
                soc_matrix[idx, t]       = soc
                demand_matrix[idx, t]    = kw_domanda
                batt_use_matrix[idx, t]  = kw_da_batt
                kw_stallo_matrix[idx, t] = kw_per_stallo

        # Flush sessioni ancora attive a fine giornata (non completate)
        for i_st, st_ in enumerate(stalli):
            if st_['kwh'] > 0.0 and (kwh_def3[i_st] > 0 or kwh_def4[i_st] > 0):
                kw_n = st_['kw_max']
                if kw_n > 0:
                    slot_extra3_list.append(kwh_def3[i_st] / kw_n / SLOT_H)
                    slot_extra4_list.append(kwh_def4[i_st] / kw_n / SLOT_H)

        return soc, soc_min, en_mancante, n_slot_stress, slot_occupati, kwh_erogati_tot, n_episodi_bassa, giorno_ha_bassa, slot_batt_attiva, slot_batt_soglia, slot_pu_binding, slot_stallo_binding, dist_attivi, delta_richiesto_list, delta_kwmax_list, n_episodi_b, giorno_ha_b, delta_b_list, slot_extra3_list, slot_extra4_list, n_ric, slot_con_auto

    # ── WARM-UP: stima SOC iniziale realistico ────────────────────────────────
    # Prima giornata di warm-up: worst case (batteria a 0 + intera notte di ricarica)
    soc_wup = min(cap_totale, (ore_pre + ore_post) * P_carica_tot)
    soc_fine_list = []

    for _ in range(n_warmup):
        soc_fine_op, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _ = simula_giornata(soc_wup, registra=False)
        # Ricarica notturna: post-operativa + pre-operativa
        soc_fine_ricaricato = min(cap_totale, soc_fine_op + (ore_post + ore_pre) * P_carica_tot)
        soc_fine_list.append(soc_fine_ricaricato)
        soc_wup = float(np.mean(soc_fine_list))

    soc_start = float(np.mean(soc_fine_list)) if soc_fine_list else 0.0

    # ── SIMULAZIONI REALI ─────────────────────────────────────────────────────
    soc_matrix       = np.zeros((n_sim, N_SLOT))
    demand_matrix    = np.zeros((n_sim, N_SLOT))
    batt_use_matrix  = np.zeros((n_sim, N_SLOT))
    kw_stallo_matrix = np.zeros((n_sim, N_SLOT))
    n_attivi_matrix  = np.zeros((n_sim, N_SLOT))
    coda_matrix      = np.zeros((n_sim, N_SLOT))

    n_giorni_scarica    = 0
    n_slot_stress_tot   = 0
    soc_min_giornaliero = np.zeros(n_sim)
    soc_fine_arr        = np.zeros(n_sim)
    energia_mancante    = np.zeros(n_sim)
    saturazione_arr     = np.zeros(n_sim)
    kwh_erogati_arr     = np.zeros(n_sim)
    coda_max_arr        = np.zeros(n_sim)
    n_slot_bassa_arr    = np.zeros(n_sim)   # slot-auto con kw < soglia per giornata
    flag_bassa_arr      = np.zeros(n_sim, dtype=bool)  # giornate con almeno un evento
    batt_attiva_arr     = np.zeros(n_sim)
    batt_soglia_arr     = np.zeros(n_sim)
    pu_binding_arr      = np.zeros(n_sim)
    stallo_binding_arr  = np.zeros(n_sim)
    dist_attivi_arr     = np.zeros((n_sim, 6), dtype=int)
    all_delta_richiesto = []
    all_delta_kwmax     = []
    # Tipo B
    n_slot_b_arr  = np.zeros(n_sim)
    flag_b_arr    = np.zeros(n_sim, dtype=bool)
    all_delta_b   = []
    all_slot_extra3 = []
    all_slot_extra4 = []
    n_ric_arr        = np.zeros(n_sim)
    slot_con_auto_arr= np.zeros(n_sim)   # slot con almeno 1 auto per giornata

    SLOT_24H = int(24 * 60 / SLOT_MIN)
    denom_saturazione = SLOT_24H * int(num_pdr)

    for s in range(n_sim):
        soc_fine, soc_min, en_m, n_stress, slot_occ, kwh_er, n_bp, flag_bp, s_batt_att, s_batt_sog, s_pu_bind, s_st_bind, s_dist, d_rich, d_kwmax, n_bp_b, flag_bp_b, d_b, se3, se4, n_ric_s, s_con_auto = simula_giornata(soc_start, registra=True, idx=s)
        soc_min_giornaliero[s] = soc_min
        soc_fine_arr[s]        = soc_fine
        energia_mancante[s]    = en_m
        n_slot_stress_tot     += n_stress
        saturazione_arr[s]     = slot_occ / denom_saturazione * 100
        kwh_erogati_arr[s]     = kwh_er
        coda_max_arr[s]        = coda_matrix[s].max()
        n_slot_bassa_arr[s]    = n_bp
        flag_bassa_arr[s]      = flag_bp
        batt_attiva_arr[s]     = s_batt_att
        batt_soglia_arr[s]     = s_batt_sog
        pu_binding_arr[s]      = s_pu_bind
        stallo_binding_arr[s]  = s_st_bind
        dist_attivi_arr[s]     = s_dist
        all_delta_richiesto.extend(d_rich)
        all_delta_kwmax.extend(d_kwmax)
        n_slot_b_arr[s] = n_bp_b
        flag_b_arr[s]   = flag_bp_b
        all_delta_b.extend(d_b)
        all_slot_extra3.extend(se3)
        all_slot_extra4.extend(se4)
        n_ric_arr[s]         = n_ric_s
        slot_con_auto_arr[s] = s_con_auto
        if soc_min <= soc_soglia:
            n_giorni_scarica += 1

    return {
        "prob":            n_giorni_scarica / n_sim * 100,
        "ore_stress":      (n_slot_stress_tot / n_sim) * SLOT_H,
        "soc_medio":       soc_matrix.mean(axis=0),
        "soc_p10":         np.percentile(soc_matrix, 10, axis=0),
        "soc_p90":         np.percentile(soc_matrix, 90, axis=0),
        # SOC minimo raggiunto durante la giornata (coerente con prob scarica)
        "soc_start_pct":    (soc_start / cap_totale * 100) if cap_totale > 0 else 0.0,
        "soc_start_kwh":    soc_start,
        "P_scarica_tot_kw": P_scarica_tot,
        "cap_totale_kwh":   cap_totale,
        "soc_soglia_kwh":   soc_soglia,
        "soc_min_p10":     (np.percentile(soc_min_giornaliero, 10) / cap_totale * 100) if cap_totale > 0 else 0.0,
        "soc_min_p90":     (np.percentile(soc_min_giornaliero, 90) / cap_totale * 100) if cap_totale > 0 else 0.0,
        "soc_min_p50":     (np.percentile(soc_min_giornaliero, 50) / cap_totale * 100) if cap_totale > 0 else 0.0,
        "soc_min_medio":   (soc_min_giornaliero.mean() / cap_totale * 100) if cap_totale > 0 else 0.0,
        "demand_medio":    demand_matrix.mean(axis=0),
        "batt_medio":      batt_use_matrix.mean(axis=0),
        "kw_stallo_medio": kw_stallo_matrix.mean(axis=0),
        # Saturazione stalli (slot occupati / slot totali 24h × N_pdr)
        "satur_media":    float(np.mean(saturazione_arr)),
        "satur_mediana":  float(np.median(saturazione_arr)),
        "satur_min":      float(np.min(saturazione_arr)),
        "satur_max":      float(np.max(saturazione_arr)),
        "satur_arr":      saturazione_arr,
        "kwh_erogati_medio":   float(np.mean(kwh_erogati_arr)),
        "kwh_erogati_mediana": float(np.median(kwh_erogati_arr)),
        "kwh_erogati_min":     float(np.min(kwh_erogati_arr)),
        "kwh_erogati_max":     float(np.max(kwh_erogati_arr)),
        "kwh_erogati_teorico": float(num_pdr * ricariche_per_pdr * kwh_medi_ricarica),
        "n_attivi_medio":  n_attivi_matrix.mean(axis=0),
        "coda_medio":      coda_matrix.mean(axis=0),
        "cap_totale":      cap_totale,
        "soc_soglia":      soc_soglia,
        "weights":         weights,
        # Array per CSV dettaglio scariche
        "_soc_min_arr":    soc_min_giornaliero,
        "_soc_fine_arr":   soc_fine_arr,
        "_en_m_arr":       energia_mancante,
        "_satur_arr_raw":  saturazione_arr,
        "_kwh_er_arr":     kwh_erogati_arr,
        "_coda_max_arr":   coda_max_arr,
        "_soc_soglia":     soc_soglia,
        # Potenza insufficiente
        "bassa_pot_giorni":     int(flag_bassa_arr.sum()),
        "bassa_pot_slot_medio": float(n_slot_bassa_arr[flag_bassa_arr].mean()) if flag_bassa_arr.any() else 0.0,  # ora = episodi medi
        "_flag_bassa_arr":      flag_bassa_arr,
        "_n_slot_bassa_arr":    n_slot_bassa_arr,
        # Debug batteria
        "batt_attiva_media":   float(np.mean(batt_attiva_arr)) * SLOT_H,   # ore/giorno
        "batt_soglia_media":   float(np.mean(batt_soglia_arr)) * SLOT_H,   # ore/giorno
        "batt_attiva_pct":     float(np.mean(batt_attiva_arr / np.maximum(slot_con_auto_arr, 1))) * 100,
        "batt_soglia_pct":     float(np.mean(batt_soglia_arr / np.maximum(slot_con_auto_arr, 1))) * 100,
        # Debug PU e stallo
        "pu_binding_medio":    float(np.mean(pu_binding_arr)),
        "pu_binding_pct":      float(np.mean(pu_binding_arr)) / max(1, N_SLOT * int(num_pdr)) * 100,
        "stallo_binding_medio":float(np.mean(stallo_binding_arr)),
        "stallo_binding_pct":  float(np.mean(stallo_binding_arr)) / max(1, N_SLOT * int(num_pdr)) * 100,
        # Distribuzione stalli attivi
        "dist_attivi_media":   dist_attivi_arr.mean(axis=0).tolist(),
        "dist_attivi_pct":     (dist_attivi_arr.mean(axis=0) / N_SLOT * 100).tolist(),
        # Delta kW negli episodi di congestione
        "delta_rich_stats":    _stats_delta(all_delta_richiesto),
        "delta_kwmax_stats":   _stats_delta(all_delta_kwmax),
        # Tipo B
        "b_giorni_critici_pct": float(flag_b_arr.sum()) / n_sim * 100,
        "b_giorni_critici_n":   int(flag_b_arr.sum()),
        "b_slot_medio":         float(n_slot_b_arr[flag_b_arr].mean()) if flag_b_arr.any() else 0.0,
        "b_delta_stats":        _stats_delta(all_delta_b),
        "slot_extra3_stats":    _stats_delta(all_slot_extra3),
        "slot_extra4_stats":    _stats_delta(all_slot_extra4),
        "ric_media_globale":    float(np.mean(n_ric_arr)),
        "ric_critiche_a":       _stats_delta(n_ric_arr[flag_bassa_arr].tolist()),
        "ric_critiche_b":       _stats_delta(n_ric_arr[flag_b_arr].tolist()),
    }

# ─── ASSI X comuni ───────────────────────────────────────────────────────────
xtv = list(range(0, N_SLOT, 12))   # un tick ogni ora (12 slot × 5 min = 60 min)
xtl = [SLOT_TIMES[i] for i in xtv]
xax = dict(tickmode="array", tickvals=xtv, ticktext=xtl)

# ─── PREVIEW ─────────────────────────────────────────────────────────────────
if not run_btn:
    st.info("👈 Imposta i parametri e premi **▶ AVVIA SIMULAZIONE**")

    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.subheader("📈 Preview distribuzione arrivi")
        w = build_weights()
        fig = go.Figure(go.Bar(x=list(range(N_SLOT)), y=w * 100, marker_color="#1a73e8"))
        fig.update_layout(xaxis=xax, yaxis_title="Probabilità (%)", height=280, template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)
    with col_b:
        st.subheader("⚡ Logica stalli")
        st.markdown(f"""
**Vincoli:**
- Max **1 auto per stallo**
- Auto in eccesso → **coda FIFO**
- Stallo libero → prima auto in coda

**Potenza per stallo attivo:**

`min({potenza_max_stallo:.0f} kW, (rete+batt) / n_attivi)`

**Esempi con {num_pdr} stalli:**

| Stalli attivi | kW/stallo |
|---|---|
| 1 | {min(potenza_max_stallo, potenza_rete_kw/1):.0f} |
| 2 | {min(potenza_max_stallo, potenza_rete_kw/2):.0f} |
| {int(num_pdr)} | {min(potenza_max_stallo, potenza_rete_kw/num_pdr):.0f} |

*solo rete, senza batteria
        """)

# ─── RISULTATI ───────────────────────────────────────────────────────────────
else:
    with st.spinner(f"⏳ Warm-up ({n_warmup} giorni) + simulazione ({n_sim} giorni × {N_SLOT} slot)..."):
        res = run_montecarlo()

    prob     = res["prob"]
    risk_cls = "risk-low" if prob < 10 else ("risk-mid" if prob < 30 else "risk-high")
    risk_lbl = "🟢 BASSO"  if prob < 10 else ("🟡 MEDIO"  if prob < 30 else "🔴 ALTO")

    # ── KPI ──────────────────────────────────────────────────────────────────
    st.subheader("📊 Risultati")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(f'<div class="metric-card {risk_cls}"><b>Probabilità scarica</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{prob:.1f}%</span><br>'
                    f'Rischio: {risk_lbl}</div>', unsafe_allow_html=True)
    with c2:
        p10 = res["soc_min_p10"]
        p90 = res["soc_min_p90"]
        st.markdown(f'<div class="metric-card"><b>SOC minimo giornaliero</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">P10: {p10:.1f}% — P90: {p90:.1f}%</span><br>'
                    f'SOC inizio giornata (warm-up): {res["soc_start_pct"]:.1f}%</div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><b>Ore stress rete/giorno</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["ore_stress"]:.1f} h</span><br>'
                    f'Domanda > {potenza_rete_kw:.0f} kW</div>', unsafe_allow_html=True)
    with c4:
        coda_max = res["coda_medio"].max()
        st.markdown(f'<div class="metric-card"><b>Coda media (picco)</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{coda_max:.1f} auto</span><br>'
                    f'Max auto in attesa</div>', unsafe_allow_html=True)
    with c5:
        fabb = num_pdr * ricariche_per_pdr * kwh_medi_ricarica
        st.markdown(f'<div class="metric-card"><b>Fabbisogno giornaliero</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{fabb:.0f} kWh</span><br>'
                    f'Capacità batteria: {res["cap_totale"]:.0f} kWh</div>', unsafe_allow_html=True)

    # ── KPI POTENZA INSUFFICIENTE ─────────────────────────────────────────────
    st.subheader("⚡ Occorrenze Potenza Insufficiente")
    tab_a, tab_b = st.tabs([
        "🔴 Tipo A — Sistema sotto soglia (auto veloci)",
        "🟠 Tipo B — Sistema sotto richiesta auto (tutte)"
    ])

    with tab_a:
        st.caption(
            f"Condizione: **kW_assegnato < min(kW_max, kWh_res/dt)** (congestione) "
            f"AND **kW_max×coeff > {kw_soglia_auto:.0f} kW** (S_auto: auto veloce) "
            f"AND **kW_max×coeff > {kw_soglia_sistema:.0f} kW** (S_sis: chiede più della soglia sistema) "
            f"— 1 episodio per sessione"
        )
        bp_giorni = res["bassa_pot_giorni"]
        bp_prob   = bp_giorni / n_sim * 100
        bp_cls    = "risk-low" if bp_prob < 10 else ("risk-mid" if bp_prob < 30 else "risk-high")
        bpa1, bpa2 = st.columns(2)
        with bpa1:
            st.markdown(f'<div class="metric-card {bp_cls}"><b>Giornate critiche Tipo A</b><br>'
                        f'<span style="font-size:1.6rem;font-weight:700">{bp_giorni} gg ({bp_prob:.1f}%)</span><br>'
                        f'kW_assegnato &lt; min(kW_max, kWh/dt) con kW_max×coeff &gt; {kw_soglia_potenza:.0f} kW</div>', unsafe_allow_html=True)
        with bpa2:
            st.markdown(f'<div class="metric-card"><b>Episodi medi per giornata critica</b><br>'
                        f'<span style="font-size:1.6rem;font-weight:700">{res["bassa_pot_slot_medio"]:.1f} episodi</span><br>'
                        f'Water-fill assegna meno di min(kW_max, kWh/dt) — auto veloce sopra soglie</div>', unsafe_allow_html=True)
        # Debug ricariche giornate critiche A
        ra = res["ric_critiche_a"]
        if ra["n"] > 0:
            st.caption(
                f"📊 Ricariche/giorno nelle giornate critiche A — "
                f"Media: **{ra['media']:.1f}** | Mediana: {ra['mediana']:.1f} | "
                f"Min: {ra['min']:.0f} | Max: {ra['max']:.0f} | "
                f"(media globale: {res['ric_media_globale']:.1f})"
            )

    with tab_b:
        st.caption(
            f"Condizione: **kW_assegnato < min(kW_max, kWh_res/dt)** (congestione) "
            f"— nessun filtro velocità, nessuna soglia — 1 episodio per sessione"
        )
        b_giorni = res["b_giorni_critici_n"]
        b_prob   = res["b_giorni_critici_pct"]
        b_cls    = "risk-low" if b_prob < 10 else ("risk-mid" if b_prob < 30 else "risk-high")
        bpb1, bpb2 = st.columns(2)
        with bpb1:
            st.markdown(f'<div class="metric-card {b_cls}"><b>Giornate critiche Tipo B</b><br>'
                        f'<span style="font-size:1.6rem;font-weight:700">{b_giorni} gg ({b_prob:.1f}%)</span><br>'
                        f'kW_assegnato &lt; min(kW_max, kWh/dt) — qualsiasi auto congestionata</div>', unsafe_allow_html=True)
        with bpb2:
            st.markdown(f'<div class="metric-card"><b>Episodi medi per giornata critica</b><br>'
                        f'<span style="font-size:1.6rem;font-weight:700">{res["b_slot_medio"]:.1f} episodi</span><br>'
                        f'Water-fill assegna meno di min(kW_max, kWh/dt) — nessun filtro</div>', unsafe_allow_html=True)
        b_ds = res["b_delta_stats"]
        if b_ds["n"] > 0:
            st.caption(f"Deficit medio Tipo B: **{b_ds['media']:.1f} kW** | mediana {b_ds['mediana']:.1f} | min {b_ds['min']:.1f} | max {b_ds['max']:.1f} — su {b_ds['n']} episodi totali")
        # Debug ricariche giornate critiche B
        rb = res["ric_critiche_b"]
        if rb["n"] > 0:
            st.caption(
                f"📊 Ricariche/giorno nelle giornate critiche B — "
                f"Media: **{rb['media']:.1f}** | Mediana: {rb['mediana']:.1f} | "
                f"Min: {rb['min']:.0f} | Max: {rb['max']:.0f} | "
                f"(media globale: {res['ric_media_globale']:.1f})"
            )


    # ── DEBUG BATTERIA ────────────────────────────────────────────────────────
    with st.expander("🔍 Debug: parametri sistema simulati", expanded=True):
        d1, d2, d3, d4, d5 = st.columns(5)
        with d1:
            st.metric("SOC inizio (kWh)", f"{res['soc_start_kwh']:.1f}")
        with d2:
            st.metric("Capacità totale (kWh)", f"{res['cap_totale_kwh']:.1f}")
        with d3:
            st.metric("SOC soglia (kWh)", f"{res['soc_soglia_kwh']:.1f}")
        with d4:
            st.metric("P scarica tot (kW)", f"{res['P_scarica_tot_kw']:.1f}")
        with d5:
            st.metric("P rete (kW)", f"{potenza_rete_kw:.1f}")
        st.caption(
            f"P disponibile max = rete + scarica = {potenza_rete_kw + res['P_scarica_tot_kw']:.1f} kW — "
            f"con {int(num_pdr)} stalli attivi → {(potenza_rete_kw + res['P_scarica_tot_kw']) / int(num_pdr):.1f} kW/stallo"
        )

    with st.expander("🔋 Debug: contributo batteria negli slot operativi", expanded=False):
        batt_att_ore = res["batt_attiva_media"]
        batt_sog_ore = res["batt_soglia_media"]
        batt_att_pct = res["batt_attiva_pct"]
        batt_sog_pct = res["batt_soglia_pct"]
        ore_op       = ORA_FINE - ORA_INIZIO
        batt_inattiva_ore = max(0, ore_op - batt_att_ore - batt_sog_ore)
        batt_inattiva_pct = max(0, 100 - batt_att_pct - batt_sog_pct)

        db1, db2, db3 = st.columns(3)
        with db1:
            st.markdown(f'<div class="metric-card"><b>Batteria contribuisce</b><br>'
                        f'<span style="font-size:1.4rem;font-weight:700">{batt_att_ore:.1f}h/gg</span><br>'
                        f'{batt_att_pct:.1f}% degli slot con auto</div>', unsafe_allow_html=True)
        with db2:
            cls = "risk-high" if batt_sog_pct > 30 else ("risk-mid" if batt_sog_pct > 10 else "")
            st.markdown(f'<div class="metric-card {cls}"><b>Batteria bloccata a soglia</b><br>'
                        f'<span style="font-size:1.4rem;font-weight:700">{batt_sog_ore:.1f}h/gg</span><br>'
                        f'{batt_sog_pct:.1f}% degli slot con auto</div>', unsafe_allow_html=True)
        with db3:
            st.markdown(f'<div class="metric-card"><b>Batteria non necessaria</b><br>'
                        f'<span style="font-size:1.4rem;font-weight:700">{batt_inattiva_ore:.1f}h/gg</span><br>'
                        f'{batt_inattiva_pct:.1f}% degli slot con auto</div>', unsafe_allow_html=True)

        if batt_sog_pct > 20:
            st.warning(
                f"⚠️ La batteria è bloccata alla soglia SOC per il {batt_sog_pct:.0f}% degli slot con auto attive. "
                f"Aggiungere più batterie non riduce le occorrenze di potenza insufficiente: "
                f"la batteria esaurisce il SOC utile prima della fine della giornata. "
                f"Per ridurre le occorrenze occorre aumentare la **potenza di rete** o abbassare le **soglie**."
            )
        else:
            st.info(
                f"ℹ️ La batteria è bloccata alla soglia solo il {batt_sog_pct:.0f}% del tempo. "
                f"Aggiungere batterie potrebbe ridurre marginalmente le occorrenze di potenza insufficiente."
            )

    with st.expander("🅿️ Debug: distribuzione stalli attivi per slot", expanded=False):
        dist_pct  = res["dist_attivi_pct"]
        dist_slot = res["dist_attivi_media"]
        labels    = ["0 stalli", "1 stallo", "2 stalli", "3 stalli", "4 stalli", "≥5 stalli"]
        colors_d  = ["#e0e0e0", "#64b5f6", "#1a73e8", "#f9a825", "#e53935", "#7b1fa2"]

        cols = st.columns(6)
        for i, (col, lbl, pct, slot) in enumerate(zip(cols, labels, dist_pct, dist_slot)):
            with col:
                st.markdown(
                    f'<div class="metric-card" style="text-align:center;border-top:4px solid {colors_d[i]}">'
                    f'<b>{lbl}</b><br>'
                    f'<span style="font-size:1.4rem;font-weight:700;color:{colors_d[i]}">{pct:.1f}%</span><br>'
                    f'<span style="font-size:0.85rem;color:#666">{slot:.1f} slot/gg</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )
        st.caption(
            f"Percentuale degli slot operativi ({N_SLOT} slot totali) con quel numero di stalli attivi contemporaneamente. "
            f"La somma è 100%."
        )

    with st.expander("📉 Debug: deficit potenza negli episodi di congestione", expanded=False):
        def _fmt(v, unit="kW"):
            return f"{v:.1f} {unit}" if v is not None else "—"

        def _mostra_delta(dr, dk, label_extra=""):
            if dr["n"] == 0:
                st.info("Nessun episodio registrato.")
                return
            st.caption(f"Statistiche su **{dr['n']} episodi** totali (tutte le simulazioni).{label_extra}")
            st.markdown("**Δ₁ = kw_max_auto × coeff_picco − kw_assegnato_i** (deficit rispetto alla richiesta di picco — potenza reale water-fill)")
            cols1 = st.columns(4)
            for col, lbl, val in zip(cols1, ["Media","Mediana","Minimo","Massimo"],
                                     [dr["media"], dr["mediana"], dr["min"], dr["max"]]):
                with col:
                    st.metric(lbl, _fmt(val))
            st.markdown("**Δ₂ = kw_max_auto − kw_assegnato_i** (deficit rispetto alla velocità nominale auto — potenza reale water-fill)")
            cols2 = st.columns(4)
            for col, lbl, val in zip(cols2, ["Media","Mediana","Minimo","Massimo"],
                                     [dk["media"], dk["mediana"], dk["min"], dk["max"]]):
                with col:
                    st.metric(lbl, _fmt(val))
            st.caption("Δ₁ include il coefficiente di picco → misura quanto manca rispetto alla richiesta di picco. "
                       "Δ₂ usa kw_max nudo → misura il deficit rispetto alla velocità nominale. "
                       "Entrambi usano kw_assegnato_i dal water-fill (non la quota equa). Δ₁ ≥ Δ₂ sempre.")

        dtab_a, dtab_b = st.tabs([
            "🔴 Tipo A — Auto veloci",
            "🟠 Tipo B — Tutte le auto"
        ])
        with dtab_a:
            _mostra_delta(res["delta_rich_stats"], res["delta_kwmax_stats"])
        with dtab_b:
            db = res["b_delta_stats"]
            # Per Tipo B Δ₂ coincide con Δ₁ (non c'è coeff nel check B), usiamo stesso delta
            _mostra_delta(db, db, " (Δ₁ = Δ₂ perché Tipo B usa kw_max×coeff senza filtro separato)")

        # ── Slot extra ────────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("**⏱ Slot extra per sessione penalizzata** (ritardo rispetto allo scenario ideale)")
        se3 = res["slot_extra3_stats"]
        se4 = res["slot_extra4_stats"]
        if se3["n"] == 0:
            st.info("Nessuna sessione penalizzata registrata.")
        else:
            st.caption(
                f"Su **{se3['n']} sessioni penalizzate** (almeno 1 slot in deficit). "
                f"Slot extra = kWh_deficit_totali / kW_ideale / dt"
            )
            se_tab3, se_tab4 = st.tabs([
                "Opzione 3 — Tipo A (auto veloci)",
                "Opzione 4 — Tipo B (tutte le auto)"
            ])
            with se_tab3:
                sc3 = st.columns(4)
                for col, lbl, val in zip(sc3, ["Media","Mediana","Minimo","Massimo"],
                                         [se3["media"], se3["mediana"], se3["min"], se3["max"]]):
                    with col:
                        st.metric(lbl, f"{val:.2f} slot" if val is not None else "—")
                        st.caption(f"≈ {val*5:.1f} min" if val is not None else "")
            with se_tab4:
                sc4 = st.columns(4)
                for col, lbl, val in zip(sc4, ["Media","Mediana","Minimo","Massimo"],
                                         [se4["media"], se4["mediana"], se4["min"], se4["max"]]):
                    with col:
                        st.metric(lbl, f"{val:.2f} slot" if val is not None else "—")
                        st.caption(f"≈ {val*5:.1f} min" if val is not None else "")
            st.caption(
                "Opzione 3: sessioni episodi Tipo A (auto veloci). "
                "Opzione 4: divide per kW_max nudo — ritardo rispetto alla velocità nominale dell'auto. "
                "Opzione 3 ≤ Opzione 4 (denominatore più grande → meno slot extra)."
            )

    with st.expander("⚡ Debug: vincolo Power Unit", expanded=False):
        pu_bind_slot  = res["pu_binding_medio"]
        pu_bind_pct   = res["pu_binding_pct"]
        glob_bind_pct = max(0, 100 - pu_bind_pct - res["stallo_binding_pct"])
        pu1, pu2, pu3 = st.columns(3)
        with pu1:
            cls = "risk-high" if pu_bind_pct > 30 else ("risk-mid" if pu_bind_pct > 10 else "")
            st.markdown(f'<div class="metric-card {cls}"><b>PU vincolo binding</b><br>'
                        f'<span style="font-size:1.4rem;font-weight:700">{pu_bind_slot:.0f} slot-stallo/gg</span><br>'
                        f'{pu_bind_pct:.1f}% degli slot-stallo totali</div>', unsafe_allow_html=True)
        with pu2:
            st.markdown(f'<div class="metric-card"><b>Rete+batt vincolo binding</b><br>'
                        f'<span style="font-size:1.4rem;font-weight:700">{glob_bind_pct:.1f}%</span><br>'
                        f'degli slot-stallo totali</div>', unsafe_allow_html=True)
        with pu3:
            st.markdown(f'<div class="metric-card"><b>Limite stallo raggiunto</b><br>'
                        f'<span style="font-size:1.4rem;font-weight:700">{res["stallo_binding_pct"]:.1f}%</span><br>'
                        f'degli slot-stallo totali</div>', unsafe_allow_html=True)
        if pu_bind_pct > 20:
            st.warning(f"⚠️ La Power Unit è il vincolo stringente nel {pu_bind_pct:.0f}% dei casi. "
                       f"Aumentare la potenza PU (attualmente {potenza_pu_kw:.0f} kW) ridurrebbe le occorrenze.")
        else:
            st.info(f"ℹ️ La Power Unit raramente è il vincolo stringente ({pu_bind_pct:.0f}%). "
                    f"Il collo di bottiglia è il budget globale (rete+batt), non la PU.")

    with st.expander("🔌 Debug: vincolo potenza per stallo", expanded=False):
        st_bind_pct  = res["stallo_binding_pct"]
        st_bind_slot = res["stallo_binding_medio"]
        s1, s2 = st.columns(2)
        with s1:
            cls = "risk-high" if st_bind_pct > 30 else ("risk-mid" if st_bind_pct > 10 else "")
            st.markdown(f'<div class="metric-card {cls}"><b>Limite stallo raggiunto</b><br>'
                        f'<span style="font-size:1.4rem;font-weight:700">{st_bind_slot:.0f} slot-stallo/gg</span><br>'
                        f'{st_bind_pct:.1f}% degli slot-stallo totali</div>', unsafe_allow_html=True)
        with s2:
            st.markdown(f'<div class="metric-card"><b>Potenza max stallo (kW)</b><br>'
                        f'<span style="font-size:1.4rem;font-weight:700">{potenza_max_stallo:.0f} kW</span><br>'
                        f'Limite fisico configurato</div>', unsafe_allow_html=True)
        if st_bind_pct > 20:
            st.warning(f"⚠️ Il limite fisico dello stallo ({potenza_max_stallo:.0f} kW) è raggiunto nel {st_bind_pct:.0f}% dei casi. "
                       f"Aumentarlo permetterebbe alle auto veloci di caricare più rapidamente.")
        else:
            st.info(f"ℹ️ Il limite dello stallo raramente è il vincolo attivo ({st_bind_pct:.0f}%). "
                    f"Il collo di bottiglia è altrove (rete+batt o PU).")

    # ── SATURAZIONE STALLI ───────────────────────────────────────────────────
    st.subheader("🅿️ Saturazione Stalli")
    SLOT_24H = int(24 * 60 / SLOT_MIN)
    st.caption(
        f"Slot occupati da auto in ricarica / slot totali 24h × N_pdr "
        f"({SLOT_24H} slot/giorno × {int(num_pdr)} stalli = {SLOT_24H * int(num_pdr)} slot totali). "
        f"Include solo gli slot in cui lo stallo sta effettivamente erogando energia (non cooldown, non attesa)."
    )
    sa1, sa2, sa3, sa4 = st.columns(4)
    with sa1:
        st.markdown(f'<div class="metric-card"><b>Media</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["satur_media"]:.1f}%</span><br>'
                    f'Saturazione media giornaliera</div>', unsafe_allow_html=True)
    with sa2:
        st.markdown(f'<div class="metric-card"><b>Mediana</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["satur_mediana"]:.1f}%</span><br>'
                    f'Valore centrale</div>', unsafe_allow_html=True)
    with sa3:
        st.markdown(f'<div class="metric-card risk-low"><b>Minimo</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["satur_min"]:.1f}%</span><br>'
                    f'Giornata meno trafficata</div>', unsafe_allow_html=True)
    with sa4:
        st.markdown(f'<div class="metric-card risk-mid"><b>Massimo</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["satur_max"]:.1f}%</span><br>'
                    f'Giornata più trafficata</div>', unsafe_allow_html=True)

    fig_sat = go.Figure()
    fig_sat.add_trace(go.Histogram(
        x=res["satur_arr"], nbinsx=30,
        marker_color="#1a73e8", opacity=0.8
    ))
    fig_sat.add_vline(x=res["satur_media"], line_dash="dash", line_color="#e53935",
                      annotation_text=f'Media: {res["satur_media"]:.1f}%',
                      annotation_position="top right")
    fig_sat.add_vline(x=res["satur_mediana"], line_dash="dot", line_color="#43a047",
                      annotation_text=f'Mediana: {res["satur_mediana"]:.1f}%',
                      annotation_position="top left")
    fig_sat.update_layout(
        title=f"Distribuzione saturazione stalli ({n_sim} giornate simulate)",
        xaxis_title="Saturazione (%)", yaxis_title="Numero di giornate",
        height=300, template="plotly_white", showlegend=False
    )
    st.plotly_chart(fig_sat, use_container_width=True)

    st.markdown("---")

    # ── kWh EROGATI ──────────────────────────────────────────────────────────
    st.subheader("⚡ kWh Erogati per Giornata")
    teorico = res["kwh_erogati_teorico"]
    st.caption(f"Teorico atteso: {teorico:.0f} kWh ({int(num_pdr)} stalli × {ricariche_per_pdr} ric. × {kwh_medi_ricarica:.0f} kWh). "
               f"La variabilità dipende dalla distribuzione dei kWh per sessione (σ={sigma_pct}%).")
    ke1, ke2, ke3, ke4 = st.columns(4)
    with ke1:
        st.markdown(f'<div class="metric-card"><b>Media</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["kwh_erogati_medio"]:.0f} kWh</span><br>'
                    f'Teorico: {teorico:.0f} kWh</div>', unsafe_allow_html=True)
    with ke2:
        st.markdown(f'<div class="metric-card"><b>Mediana</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["kwh_erogati_mediana"]:.0f} kWh</span><br>'
                    f'Valore centrale</div>', unsafe_allow_html=True)
    with ke3:
        st.markdown(f'<div class="metric-card risk-low"><b>Minimo</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["kwh_erogati_min"]:.0f} kWh</span><br>'
                    f'Giornata meno carica</div>', unsafe_allow_html=True)
    with ke4:
        st.markdown(f'<div class="metric-card risk-mid"><b>Massimo</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["kwh_erogati_max"]:.0f} kWh</span><br>'
                    f'Giornata più carica</div>', unsafe_allow_html=True)

    st.markdown("---")

    # ── GRAFICI ──────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "🔋 Stato Carica Batteria", "⚡ Domanda & Batteria",
        "🚗 Stalli, Coda & Potenza", "📐 Distribuzione Arrivi"])

    with tab1:
        y_p90 = (res["soc_p90"] / res["cap_totale"] * 100) if res["cap_totale"] > 0 else np.zeros(N_SLOT)
        y_p10 = (res["soc_p10"] / res["cap_totale"] * 100) if res["cap_totale"] > 0 else np.zeros(N_SLOT)
        y_med = (res["soc_medio"] / res["cap_totale"] * 100) if res["cap_totale"] > 0 else np.zeros(N_SLOT)
        fig1  = go.Figure()
        fig1.add_trace(go.Scatter(
            x=list(range(N_SLOT)) + list(range(N_SLOT))[::-1],
            y=list(y_p90) + list(y_p10)[::-1],
            fill="toself", fillcolor="rgba(26,115,232,0.12)",
            line=dict(color="rgba(0,0,0,0)"), name="P10–P90"))
        fig1.add_trace(go.Scatter(x=list(range(N_SLOT)), y=y_med,
                                   line=dict(color="#1a73e8", width=3), name="SOC medio"))
        fig1.add_trace(go.Scatter(x=list(range(N_SLOT)), y=y_p10,
                                   line=dict(color="#e53935", width=2, dash="dash"), name="SOC P10"))
        fig1.add_hline(y=soc_min_pct, line_dash="dot", line_color="red",
                       annotation_text=f"Soglia scarica ({soc_min_pct}%)")
        fig1.update_layout(xaxis=xax, yaxis=dict(title="SOC (%)", range=[0, 105]),
                           height=420, template="plotly_white",
                           title="Stato di Carica Batteria — slot 5 min")
        st.plotly_chart(fig1, use_container_width=True)

    with tab2:
        fig2 = make_subplots(rows=2, cols=1, shared_xaxes=True,
                             subplot_titles=("Domanda totale stazione (kW)",
                                             "Potenza batteria in scarica (kW)"),
                             vertical_spacing=0.12)
        fig2.add_trace(go.Scatter(x=list(range(N_SLOT)), y=res["demand_medio"],
                                   fill="tozeroy", line=dict(color="#1a73e8"), name="Domanda (kW)"), row=1, col=1)
        fig2.add_hline(y=potenza_rete_kw, line_dash="dash", line_color="orange",
                       annotation_text=f"Limite rete: {potenza_rete_kw:.0f} kW", row=1, col=1)
        fig2.add_trace(go.Bar(x=list(range(N_SLOT)), y=res["batt_medio"],
                               marker_color="#e53935", name="Batteria scarica (kW)"), row=2, col=1)
        for r in [1, 2]:
            fig2.update_xaxes(tickmode="array", tickvals=xtv, ticktext=xtl, row=r, col=1)
        fig2.update_layout(height=500, template="plotly_white")
        st.plotly_chart(fig2, use_container_width=True)

    with tab3:
        fig3 = make_subplots(rows=3, cols=1, shared_xaxes=True,
                             subplot_titles=("Stalli attivi medi",
                                             "Auto in coda (media)",
                                             "Potenza media per stallo (kW)"),
                             vertical_spacing=0.1)
        fig3.add_trace(go.Bar(x=list(range(N_SLOT)), y=res["n_attivi_medio"],
                               marker_color="#7b1fa2", name="Stalli attivi"), row=1, col=1)
        fig3.add_hline(y=num_pdr, line_dash="dash", line_color="gray",
                       annotation_text=f"Tot stalli: {int(num_pdr)}", row=1, col=1)
        fig3.add_trace(go.Bar(x=list(range(N_SLOT)), y=res["coda_medio"],
                               marker_color="#e65100", name="Auto in coda"), row=2, col=1)
        fig3.add_trace(go.Scatter(x=list(range(N_SLOT)), y=res["kw_stallo_medio"],
                                   fill="tozeroy", line=dict(color="#0097a7"), name="kW/stallo"), row=3, col=1)
        fig3.add_hline(y=potenza_max_stallo, line_dash="dash", line_color="gray",
                       annotation_text=f"Max: {potenza_max_stallo:.0f} kW", row=3, col=1)
        for r in [1, 2, 3]:
            fig3.update_xaxes(tickmode="array", tickvals=xtv, ticktext=xtl, row=r, col=1)
        fig3.update_layout(height=600, template="plotly_white")
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("La coda si forma quando arrivano più auto di stalli disponibili. "
                   "Quando la coda è alta, la potenza per stallo può salire (meno stalli attivi = più kW a testa).")

    with tab4:
        fig4 = go.Figure(go.Bar(x=list(range(N_SLOT)), y=res["weights"] * 100, marker_color="#43a047"))
        fig4.update_layout(xaxis=xax, yaxis_title="Probabilità (%)", height=300, template="plotly_white")
        st.plotly_chart(fig4, use_container_width=True)

    st.markdown("---")

    # ── REPORT NUMERICO ───────────────────────────────────────────────────────
    st.subheader("📋 Report Numerico")
    df_slot = pd.DataFrame({
        "Slot":                   SLOT_TIMES,
        "SOC Medio (%)":          (res["soc_medio"] / res["cap_totale"] * 100).round(1) if res["cap_totale"] > 0 else pd.Series([0.0]*N_SLOT).round(1),
        "SOC P10 (%)":            (res["soc_p10"]   / res["cap_totale"] * 100).round(1) if res["cap_totale"] > 0 else pd.Series([0.0]*N_SLOT).round(1),
        "SOC P90 (%)":            (res["soc_p90"]   / res["cap_totale"] * 100).round(1) if res["cap_totale"] > 0 else pd.Series([0.0]*N_SLOT).round(1),
        "SOC Medio (kWh)":        res["soc_medio"].round(1),
        "Domanda Media (kW)":     res["demand_medio"].round(1),
        "Batteria Scarica (kW)":  res["batt_medio"].round(1),
        "Stalli Attivi (media)":  res["n_attivi_medio"].round(2),
        "Auto in Coda (media)":   res["coda_medio"].round(2),
        "kW per Stallo (media)":  res["kw_stallo_medio"].round(1),
        "Prob. Arrivo (%)":       (res["weights"] * 100).round(2),
    })
    st.dataframe(df_slot, use_container_width=True, hide_index=True)

    df_par = pd.DataFrame({"Parametro": [
        "Potenza rete (kW)", "Numero stalli", "Potenza max per stallo (kW)",
        "Ricariche/stallo/giorno", "kWh medi per ricarica",
        "Variabilità energia σ (%)", "Limite inferiore energia (%)", "Limite superiore energia (%)",
        "Tempo tra ricariche stesso stallo (min)",
        "Potenza carica batteria (kW)", "Potenza scarica batteria (kW)",
        "Capacità singola (kWh)", "Numero batterie", "Capacità totale (kWh)",
        "Ore ricarica pre-operativa (0→apertura)", "Ore ricarica post-operativa (chiusura→24)",
        "SOC inizio giornata (calcolato, %)",
        "Soglia scarica (%)", "Fabbisogno giornaliero (kWh)",
        "Simulazioni", "Probabilità scarica (%)"],
    "Valore": [
        potenza_rete_kw, int(num_pdr), potenza_max_stallo,
        ricariche_per_pdr, kwh_medi_ricarica,
        sigma_pct, clip_min_pct, clip_max_pct,
        cooldown_min,
        potenza_carica_kw, potenza_scarica_kw,
        capacita_singola_kwh, num_batterie, res["cap_totale"],
        ORA_INIZIO, 24 - ORA_FINE, f"{soc_start_teorico:.1f}%",
        soc_min_pct, num_pdr * ricariche_per_pdr * kwh_medi_ricarica,
        n_sim, f"{prob:.2f}%"]})
    st.subheader("📝 Parametri")
    st.dataframe(df_par, use_container_width=True, hide_index=True)

    # ── EXPORT ───────────────────────────────────────────────────────────────
    st.subheader("💾 Esporta")
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    # CSV dettaglio giornate che sforano
    mask_scarica = res["_soc_min_arr"] <= res["_soc_soglia"]
    n_scariche   = int(mask_scarica.sum())
    cap_tot      = res["cap_totale"]

    if n_scariche > 0:
        df_scariche = pd.DataFrame({
            "Simulazione_n":         np.where(mask_scarica)[0] + 1,
            "SOC_min_kWh":           res["_soc_min_arr"][mask_scarica].round(2),
            "SOC_min_pct":           (res["_soc_min_arr"][mask_scarica] / cap_tot * 100).round(2) if cap_tot > 0 else np.zeros(n_scariche).round(2),
            "SOC_fine_operativo_kWh": res["_soc_fine_arr"][mask_scarica].round(2),
            "SOC_fine_operativo_pct": (res["_soc_fine_arr"][mask_scarica] / cap_tot * 100).round(2) if cap_tot > 0 else np.zeros(n_scariche).round(2),
            "kWh_erogati":           res["_kwh_er_arr"][mask_scarica].round(2),
            "Energia_mancante_kWh":  res["_en_m_arr"][mask_scarica].round(2),
            "Saturazione_pct":       res["_satur_arr_raw"][mask_scarica].round(2),
            "Coda_max_auto":         res["_coda_max_arr"][mask_scarica].astype(int),
        })
        csv_scariche = df_scariche.to_csv(index=False, sep=";", decimal=",")
    else:
        csv_scariche = "Nessuna giornata con scarica\n"

    ca, cb, cc = st.columns(3)
    with ca:
        csv_out = (f"=== PARAMETRI ===\n{df_par.to_csv(index=False, sep=';', decimal=',')}\n\n"
                   f"=== SLOT ===\n{df_slot.to_csv(index=False, sep=';', decimal=',')}\n"
                   f"Generato: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
        st.download_button("⬇️ CSV riepilogo", data=csv_out, file_name=f"ev_risk_{ts}.csv",
                           mime="text/csv", use_container_width=True)
    with cb:
        st.download_button("⬇️ JSON",
                           data=json.dumps({
                               "parametri": dict(zip(df_par["Parametro"], df_par["Valore"])),
                               "slot": df_slot.to_dict(orient="records"),
                               "prob_scarica_pct": round(prob, 2),
                               "generato": datetime.now().isoformat()},
                               indent=2, ensure_ascii=False),
                           file_name=f"ev_risk_{ts}.json",
                           mime="application/json", use_container_width=True)
    with cc:
        lbl = f"⬇️ CSV scariche ({n_scariche} gg)" if n_scariche > 0 else "✅ Nessuna scarica"
        st.download_button(lbl, data=csv_scariche,
                           file_name=f"ev_scariche_{ts}.csv",
                           mime="text/csv", use_container_width=True,
                           disabled=(n_scariche == 0))

    # ── INTERPRETAZIONE ───────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("💡 Interpretazione")

    # Coerenza: se prob scarica > 0, SOC min P10 deve essere <= soglia
    st.info(f"ℹ️ **Come leggere i risultati:** la probabilità di scarica ({prob:.1f}%) indica quante giornate "
            f"simulate hanno raggiunto il SOC minimo ≤ soglia ({soc_min_pct}%). "
            f"Il SOC P10 nel grafico mostra l'andamento ora per ora nello scenario peggiore, "
            f"e può risalire dopo il picco (la rete ricarica la batteria nei momenti liberi). "
            f"Il SOC minimo raggiunto (P10) di **{res['soc_min_p10']:.1f}%** è il punto più basso toccato "
            f"nelle giornate peggiori — questa è la metrica coerente con la probabilità di scarica.")
    if prob < 5:
        st.success(f"✅ **Rischio molto basso ({prob:.1f}%)** — Sistema ben dimensionato.")
    elif prob < 15:
        st.info(f"ℹ️ **Rischio basso ({prob:.1f}%)** — Adeguato, monitorare i giorni ad alta affluenza.")
    elif prob < 30:
        st.warning(f"⚠️ **Rischio medio ({prob:.1f}%)** — Circa 1 giorno su {100/prob:.0f} la batteria si esaurisce. "
                   "Valutare aumento capacità o riduzione picchi.")
    else:
        st.error(f"🚨 **Rischio alto ({prob:.1f}%)** — Batteria sottodimensionata rispetto alla domanda attesa.")

    if res["ore_stress"] > 1:
        st.warning(f"⚡ Rete saturata mediamente **{res['ore_stress']:.1f} ore/giorno**: "
                   "la batteria copre i picchi in queste fasce.")

    if res["coda_medio"].max() > 0.5:
        ora_picco_coda = SLOT_TIMES[int(res["coda_medio"].argmax())]
        st.info(f"🚗 Coda media di **{res['coda_medio'].max():.1f} auto** nel picco ({ora_picco_coda}). "
                f"Valutare l'aggiunta di stalli se il tempo di attesa è critico.")
