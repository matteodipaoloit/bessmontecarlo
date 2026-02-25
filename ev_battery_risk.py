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

    st.subheader("🕐 Orario Operativo")
    col_h1, col_h2 = st.columns(2)
    with col_h1:
        ORA_INIZIO = st.number_input("Ora apertura", min_value=0, max_value=23, value=7, step=1)
    with col_h2:
        ORA_FINE   = st.number_input("Ora chiusura", min_value=1, max_value=24, value=23, step=1)

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
    potenza_rete_kw      = st.number_input("Potenza dalla rete (kW) — limite fisso", 0.0, 10000.0, 150.0, 10.0)
    num_pdr              = st.number_input("Numero stalli (PDR)", 1, 100, 4)
    potenza_max_stallo   = st.number_input("Potenza massima per stallo (kW)", 10.0, 400.0, 150.0, 10.0,
                                           help="Limite fisso del singolo stallo. Se più stalli attivi, la potenza disponibile si divide tra loro.")
    ricariche_per_pdr    = st.number_input("Ricariche giornaliere per stallo", 1, 50, 8)
    kwh_medi_ricarica    = st.number_input("kWh medi per ricarica", 1.0, 200.0, 40.0, 5.0)

    with st.expander("⚡ Power Unit", expanded=False):
        num_pu           = st.number_input("Numero Power Unit", 1, 50, 2,
                                           help="Numero totale di Power Unit nella stazione.")
        pdr_per_pu       = st.number_input("PDR per Power Unit", 1, 20, 2,
                                           help="Numero di stalli collegati a ogni Power Unit.")
        potenza_pu_kw    = st.number_input("Potenza massima per Power Unit (kW)", 10.0, 2000.0, 150.0, 10.0,
                                           help="Limite aggregato di ogni PU. Se più PDR attivi sulla stessa PU, la potenza si divide tra loro.")
        st.caption(f"Potenza max per PDR (tutti attivi sulla stessa PU): {potenza_pu_kw/pdr_per_pu:.0f} kW")

    with st.expander("⚙️ Variabilità energia per ricarica", expanded=False):
        sigma_pct = st.slider(
            "Variabilità σ (% della media)",
            min_value=0, max_value=50, value=20, step=1,
            help="Deviazione standard come % di E_avg. 0% = tutte le auto caricano esattamente E_avg.")
        clip_min_pct = st.slider(
            "Limite inferiore (% della media)",
            min_value=1, max_value=80, value=30, step=1,
            help="Energia minima che un'auto può richiedere. Es. 30% → con E_avg=40kWh il minimo è 12kWh.")
        clip_max_pct = st.slider(
            "Limite superiore (% della media)",
            min_value=110, max_value=300, value=170, step=5,
            help="Energia massima che un'auto può richiedere. Es. 170% → con E_avg=40kWh il massimo è 68kWh.")
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
            "Potenza max media delle auto (kW)", 10.0, 500.0, 150.0, 10.0,
            help="Velocità di ricarica massima accettata dall'auto in media. Ogni sessione ha il suo valore casuale.")
        kw_auto_sigma_pct = st.slider(
            "Variabilità σ (% della media)", 0, 50, 20, 1,
            help="Dispersione intorno alla media. Es. 20% con media 150 kW → σ = 30 kW.")
        kw_auto_min = st.number_input(
            "Minimo (kW)", 1.0, 500.0, max(1.0, kw_auto_media * 0.3), 5.0,
            help="Potenza minima accettata dall'auto (clip inferiore della distribuzione).")
        kw_auto_max = st.number_input(
            "Massimo (kW)", 1.0, 1000.0, min(500.0, kw_auto_media * 2.0), 5.0,
            help="Potenza massima accettata dall'auto (clip superiore della distribuzione).")
        kw_auto_sigma = kw_auto_media * kw_auto_sigma_pct / 100
        st.caption(
            f"Distribuzione: Normal({kw_auto_media:.0f}, {kw_auto_sigma:.0f}) "
            f"clip [{kw_auto_min:.0f} – {kw_auto_max:.0f}] kW"
        )
        kw_soglia_sistema = st.number_input(
            "Soglia potenza sistema (kW)", 1.0, 500.0, 100.0, 10.0,
            help="Il sistema è considerato insufficiente quando (rete+batt)/stalli_attivi_PU scende sotto questa soglia."
        )
        kw_soglia_auto = st.number_input(
            "Soglia potenza auto (kW)", 1.0, 500.0, 100.0, 10.0,
            help="L'auto è considerata 'veloce' (e quindi penalizzata dal sistema congestionato) "
                 "quando kw_max_auto × coeff_picco supera questa soglia."
        )
        coeff_picco_pct = st.slider(
            "Coefficiente picco potenza auto (%)", 100, 200, 100, 5,
            help="Solo per il check potenza insufficiente: la velocità max dell'auto viene "
                 "moltiplicata per questo coefficiente. Es. 150% → un'auto da 100 kW viene "
                 "trattata come se potesse richiedere 150 kW al picco."
        )
        coeff_picco = coeff_picco_pct / 100.0
        # Alias per compatibilità con la KPI label
        kw_soglia_potenza = kw_soglia_sistema
    potenza_carica_kw    = st.number_input("Potenza di carica batteria (kW)",  1.0, 5000.0, 100.0, 10.0)
    potenza_scarica_kw   = st.number_input("Potenza di scarica batteria (kW)", 1.0, 5000.0, 150.0, 10.0)
    capacita_singola_kwh = st.number_input("Capacità singola batteria (kWh)",  1.0, 2000.0, 200.0, 10.0)
    num_batterie         = st.number_input("Numero batterie", 0, 20, 2)

    st.subheader("📊 Distribuzione Arrivi")
    distribuzione = st.selectbox("Tipo distribuzione",
                                 ["Doppia Gaussiana (mattina + sera)", "Singola Gaussiana (picco unico)"])

    # Valori default picchi clampati nell'intervallo operativo
    p1_default = max(ORA_INIZIO, min(ORA_FINE - 1, 10))
    p2_default = max(ORA_INIZIO, min(ORA_FINE - 1, 18))
    pm_default = max(ORA_INIZIO, min(ORA_FINE - 1, 12))

    if distribuzione == "Doppia Gaussiana (mattina + sera)":
        c1, c2 = st.columns(2)
        with c1:
            picco1 = st.slider("Picco mattina (h)", ORA_INIZIO, ORA_FINE - 1, p1_default)
            sigma1 = st.slider("Ampiezza mat. (h)", 0.5, 4.0, 1.5, 0.5)
            peso1  = st.slider("% mattina", 10, 90, 40)
        with c2:
            picco2 = st.slider("Picco sera (h)", ORA_INIZIO, ORA_FINE - 1, p2_default)
            sigma2 = st.slider("Ampiezza sera (h)", 0.5, 4.0, 2.0, 0.5)
            st.metric("% sera", 100 - peso1)
        peso2 = 100 - peso1
    else:
        picco1 = st.slider("Ora picco", ORA_INIZIO, ORA_FINE - 1, pm_default)
        sigma1 = st.slider("Ampiezza (h)", 0.5, 4.0, 2.5, 0.5)
        picco2, sigma2, peso1, peso2 = 0, 1, 100, 0

    st.subheader("🚗 Tempi operativi")
    cooldown_min = st.number_input("Tempo tra ricariche sullo stesso stallo (min)",
                                   min_value=0, max_value=60, value=5, step=5,
                                   help="Minuti di attesa dopo ogni ricarica (spostamento auto, pulizia, ecc.). Risoluzione: 5 minuti (= 1 slot).")
    cooldown_slot = int(round(cooldown_min / SLOT_MIN)) if cooldown_min > 0 else 0

    st.subheader("🎲 Simulazione")
    n_sim       = st.selectbox("Simulazioni Montecarlo", [500, 1000, 2000, 5000], index=1)
    n_warmup    = st.selectbox("Simulazioni warm-up (stima SOC iniziale)", [50, 100, 200, 500], index=1,
                               help="Giornate simulate per stimare il SOC realistico a inizio giornata operativa, prima delle simulazioni principali. Non contribuiscono alle statistiche finali.")
    soc_min_pct = st.slider("Soglia 'batteria scarica' (%)", 0, 30, 5)

    # Calcola SOC iniziale teorico (ricarica notturna in due spezzoni)
    ore_pre_prev       = ORA_INIZIO
    ore_post_prev      = 24 - ORA_FINE
    P_carica_tot_prev  = min(potenza_rete_kw, potenza_carica_kw * num_batterie)
    kwh_ricaricabili   = (ore_pre_prev + ore_post_prev) * P_carica_tot_prev
    cap_teorica        = capacita_singola_kwh * num_batterie
    soc_start_teorico  = min(100.0, kwh_ricaricabili / cap_teorica * 100) if cap_teorica > 0 else 100.0
    st.info(
        f"🔋 SOC a inizio giornata (stimato worst-case): **{soc_start_teorico:.1f}%**\n\n"
        f"Ricarica: {ore_post_prev}h post ({ORA_FINE}:00→24:00) + "
        f"{ore_pre_prev}h pre (0:00→{ORA_INIZIO}:00) = "
        f"{ore_pre_prev + ore_post_prev}h × {P_carica_tot_prev:.0f} kW = "
        f"{kwh_ricaricabili:.0f} kWh su {cap_teorica:.0f} kWh. "
        f"Il valore reale viene stimato dal warm-up prima della simulazione."
    )

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

def run_montecarlo():
    np.random.seed(42)
    cap_totale    = capacita_singola_kwh * num_batterie
    soc_soglia    = cap_totale * soc_min_pct / 100.0
    weights       = build_weights()
    ricariche_tot = int(num_pdr * ricariche_per_pdr)

    # Potenze totali del sistema batteria
    P_carica_tot  = min(potenza_rete_kw, potenza_carica_kw * num_batterie)
    P_scarica_tot = potenza_scarica_kw * num_batterie
    kwh_cap_giornaliero = float("inf")  # nessun limite sul totale erogato giornaliero

    # Ore di ricarica notturna (due spezzoni separati)
    ore_pre  = ORA_INIZIO       # 0:00 → ORA_INIZIO
    ore_post = 24 - ORA_FINE    # ORA_FINE → 24:00

    # ── Funzione interna: simula una singola giornata ─────────────────────────
    def simula_giornata(soc_inizio, registra=False, idx=0):
        """
        Simula una giornata operativa partendo da soc_inizio.
        Se registra=True, salva i dati nelle matrici (solo per simulazioni reali).
        Restituisce (soc_fine_operativo, soc_min_giornata, energia_mancante_kwh).
        """
        soc     = soc_inizio
        soc_min = soc_inizio

        slot_arrivo = np.random.choice(N_SLOT, size=ricariche_tot, p=weights)
        kwh_target  = np.random.normal(kwh_medi_ricarica, kwh_medi_ricarica * sigma_pct / 100, size=ricariche_tot)
        kwh_target  = np.clip(kwh_target,
                              kwh_medi_ricarica * clip_min_pct / 100,
                              kwh_medi_ricarica * clip_max_pct / 100)
        # Potenza max accettata da ogni singola auto
        kw_max_per_auto = np.random.normal(kw_auto_media, kw_auto_sigma, size=ricariche_tot)
        kw_max_per_auto = np.clip(kw_max_per_auto, kw_auto_min, kw_auto_max)

        coda   = []  # ogni elemento: (kwh_residui, kw_max_auto)
        # Assegna ogni stallo alla sua PU (0-indexed)
        stalli = [{'kwh': 0.0, 'cooldown': 0, 'kw_max': 0.0,
                   'pu': i // int(pdr_per_pu)} for i in range(int(num_pdr))]
        arrivi_per_slot = {t: [] for t in range(N_SLOT)}
        for i in range(ricariche_tot):
            arrivi_per_slot[slot_arrivo[i]].append((kwh_target[i], kw_max_per_auto[i]))

        en_mancante     = 0.0
        n_slot_stress   = 0
        slot_occupati   = 0
        kwh_erogati_tot = 0.0
        n_episodi_bassa  = 0   # episodi (transizioni ok→bassa) per stallo
        giorno_ha_bassa  = False
        stallo_in_bassa  = [False] * int(num_pdr)  # traccia se stallo già in bassa pot.

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
                    if kwh_erogati_tot + coda[0][0] <= kwh_cap_giornaliero:
                        kwh_s, kw_max_s = coda.pop(0)
                        st_['kwh']   = kwh_s
                        st_['kw_max'] = kw_max_s
                    else:
                        break

            n_attivi = sum(1 for st_ in stalli if st_['kwh'] > 0.0)
            slot_occupati += n_attivi  # ogni stallo attivo in questo slot conta 1

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

                return assegnati

            kw_assegnati = calcola_kw_assegnati()

            # Verifica soglia potenza disponibile per stallo — 1 episodio per sessione
            for i_st, st_ in enumerate(stalli):
                attivo = st_['kwh'] > 0.0
                if not attivo:
                    stallo_in_bassa[i_st] = False
                else:
                    kw_disp_st = kw_assegnati.get(i_st, 0.0)
                    if (kw_disp_st < kw_soglia_sistema
                            and st_['kw_max'] * coeff_picco > kw_soglia_auto
                            and not stallo_in_bassa[i_st]):
                        n_episodi_bassa += 1
                        giorno_ha_bassa  = True
                        stallo_in_bassa[i_st] = True

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

        return soc, soc_min, en_mancante, n_slot_stress, slot_occupati, kwh_erogati_tot, n_episodi_bassa, giorno_ha_bassa

    # ── WARM-UP: stima SOC iniziale realistico ────────────────────────────────
    # Prima giornata di warm-up: worst case (batteria a 0 + intera notte di ricarica)
    soc_wup = min(cap_totale, (ore_pre + ore_post) * P_carica_tot)
    soc_fine_list = []

    for _ in range(n_warmup):
        soc_fine_op, _, _, _, _, _, _, _ = simula_giornata(soc_wup, registra=False)
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

    SLOT_24H = int(24 * 60 / SLOT_MIN)
    denom_saturazione = SLOT_24H * int(num_pdr)

    for s in range(n_sim):
        soc_fine, soc_min, en_m, n_stress, slot_occ, kwh_er, n_bp, flag_bp = simula_giornata(soc_start, registra=True, idx=s)
        soc_min_giornaliero[s] = soc_min
        soc_fine_arr[s]        = soc_fine
        energia_mancante[s]    = en_m
        n_slot_stress_tot     += n_stress
        saturazione_arr[s]     = slot_occ / denom_saturazione * 100
        kwh_erogati_arr[s]     = kwh_er
        coda_max_arr[s]        = coda_matrix[s].max()
        n_slot_bassa_arr[s]    = n_bp
        flag_bassa_arr[s]      = flag_bp
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
    bp_giorni = res["bassa_pot_giorni"]
    bp_prob   = bp_giorni / n_sim * 100
    bp_cls    = "risk-low" if bp_prob < 10 else ("risk-mid" if bp_prob < 30 else "risk-high")
    bp1, bp2 = st.columns(2)
    with bp1:
        st.markdown(f'<div class="metric-card {bp_cls}"><b>Giornate con potenza &lt; {kw_soglia_potenza:.0f} kW</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{bp_giorni} gg ({bp_prob:.1f}%)</span><br>'
                    f'Almeno un\'auto ha ricevuto meno di {kw_soglia_potenza:.0f} kW</div>', unsafe_allow_html=True)
    with bp2:
        st.markdown(f'<div class="metric-card"><b>Occorrenze medie per giornata critica</b><br>'
                    f'<span style="font-size:1.6rem;font-weight:700">{res["bassa_pot_slot_medio"]:.1f} episodi</span><br>'
                    f'Episodio = auto che entra in zona bassa pot.</div>', unsafe_allow_html=True)


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
