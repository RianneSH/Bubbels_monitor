import os
import json
import gspread
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, date, time
from google.oauth2.service_account import Credentials
from streamlit_option_menu import option_menu
import altair as alt

# ------------------------------
# Config
# ------------------------------
st.set_page_config(page_title="Bubbel.", page_icon="🫧", layout="wide")

# ------------------------------
# Google Sheets setup
# ------------------------------
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive"
]

creds = None
client = None
json_creds = os.environ.get("GCP_SERVICE_ACCOUNT")

if json_creds:
    try:
        creds = Credentials.from_service_account_info(json.loads(json_creds), scopes=SCOPES)
        client = gspread.authorize(creds)
    except Exception as e:
        st.error(f"Kon Google credentials niet laden: {e}")
elif os.path.exists("credentials.json"):
    try:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        client = gspread.authorize(creds)
    except Exception as e:
        st.error(f"Kon credentials.json niet laden: {e}")
else:
    st.warning("Geen Google credentials gevonden — sommige functies werken niet zonder.")

sheet_baby = sheet_voorraad = sheet_bijvulling = sheet_activiteiten = sheet_instellingen = None
if client:
    try:
        book = client.open("BabyTracker")
        sheet_baby = book.worksheet("BabyRecords")
        sheet_voorraad = book.worksheet("Voorraad")
        sheet_bijvulling = book.worksheet("VoorraadBijvulling")
        sheet_activiteiten = book.worksheet("Activiteiten")
        sheet_instellingen = book.worksheet("Instellingen")
    except Exception as e:
        st.error(f"Kan Google Sheets niet openen: {e}")

# ------------------------------
# Helpers
# ------------------------------
@st.cache_data(ttl=60)
def load_data():
    baby_records = pd.DataFrame(sheet_baby.get_all_records()) if sheet_baby else pd.DataFrame()
    voorraad = pd.DataFrame(sheet_voorraad.get_all_records()) if sheet_voorraad else pd.DataFrame()
    bijvullingen = pd.DataFrame(sheet_bijvulling.get_all_records()) if sheet_bijvulling else pd.DataFrame()
    activiteiten = pd.DataFrame(sheet_activiteiten.get_all_records()) if sheet_activiteiten else pd.DataFrame()

    def parse_numeric(df, field):
        if field in df.columns:
            df[field] = pd.to_numeric(df[field].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

    if not baby_records.empty:
        for field in ['Hoeveelheid', 'Gewicht', 'Lengte', 'Temperatuur']:
            parse_numeric(baby_records, field)
        for col in ['Starttijd', 'Eindtijd']:
            if col in baby_records.columns:
                baby_records[col] = pd.to_datetime(baby_records[col], errors='coerce')

    if not bijvullingen.empty and 'Datum' in bijvullingen.columns:
        bijvullingen['Datum'] = pd.to_datetime(bijvullingen['Datum'], errors='coerce')

    if not activiteiten.empty:
        parse_numeric(activiteiten, 'Duur')
        for col in ['Starttijd', 'Eindtijd']:
            if col in activiteiten.columns:
                activiteiten[col] = pd.to_datetime(activiteiten[col], errors='coerce')

    return baby_records, voorraad, bijvullingen, activiteiten

baby_records, voorraad, bijvullingen, activiteiten = load_data()

# ------------------------------
# Instellingen
# ------------------------------
DEFAULTS = {
    'baby_naam': 'Bubbel',
    'voeding_default_type': 'Fles',
    'voeding_default_flestype': 'kunstvoeding',
    'voeding_default_ml': '100',
    'voeding_default_kolven_ml': '10',
    'voeding_default_hapje_gram': '50',
    'kunstvoeding_gram_per_schep': '4.4',
    'slaap_default_duur': '60',
    'luier_default_type': 'Nat',
    'activiteit_default_duur': '15',
    'gezondheid_default_gewicht': '5.0',
    'gezondheid_default_lengte': '50.0',
    'gezondheid_default_temp': '36.5',
}

@st.cache_data(ttl=60)
def load_instellingen():
    if sheet_instellingen is None:
        return DEFAULTS.copy()
    try:
        df = pd.DataFrame(sheet_instellingen.get_all_records())
        if df.empty or 'Sleutel' not in df.columns:
            return DEFAULTS.copy()
        inst = dict(zip(df['Sleutel'], df['Waarde']))
        for k, v in DEFAULTS.items():
            inst.setdefault(k, v)
        return inst
    except Exception:
        return DEFAULTS.copy()

def save_instelling(sleutel, waarde):
    if sheet_instellingen is None:
        return
    try:
        df = pd.DataFrame(sheet_instellingen.get_all_records())
        if 'Sleutel' in df.columns and sleutel in df['Sleutel'].values:
            row_idx = df[df['Sleutel'] == sleutel].index[0] + 2
            sheet_instellingen.update_cell(row_idx, 2, str(waarde))
        else:
            sheet_instellingen.append_row([sleutel, str(waarde)])
    except Exception as e:
        st.error(f"Kon instelling niet opslaan: {e}")

inst = load_instellingen()

# ------------------------------
# Datetime helpers
# ------------------------------
def get_device_datetime(time_input: time, date_input: date = None):
    if date_input is None:
        date_input = date.today()
    return datetime.combine(date_input, time_input)

def now_device():
    return datetime.now()

# ------------------------------
# Voorraad helpers
# ------------------------------
def get_voorraad_row(productnaam):
    """Geeft (actueel, minimum, eenheid, variant) terug voor een product."""
    if voorraad.empty:
        return 0, 0, 'stuks', ''
    mask = voorraad['Productnaam'] == productnaam
    if not mask.any():
        return 0, 0, 'stuks', ''
    r = voorraad[mask].iloc[0]
    actueel = int(pd.to_numeric(r.get('Actuele voorraad', 0), errors='coerce') or 0)
    minimum = int(pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0)
    eenheid = r.get('Eenheid', 'stuks')
    variant = r.get('Variant', '')
    return actueel, minimum, eenheid, variant

def update_voorraad(productnaam, hoeveelheid):
    if voorraad.empty or sheet_voorraad is None:
        st.warning("Voorraad niet beschikbaar")
        return
    mask = voorraad['Productnaam'] == productnaam
    if not mask.any():
        st.error("Product niet gevonden")
        return
    col = 'Actuele voorraad'
    voorraad.loc[mask, col] = (
        pd.to_numeric(voorraad.loc[mask, col], errors='coerce').fillna(0) + hoeveelheid
    ).round(1)
    voorraad.loc[voorraad[col] < 0, col] = 0
    row_idx = mask[mask].index[0] + 2
    col_idx = voorraad.columns.get_loc(col) + 1
    try:
        sheet_voorraad.update_cell(row_idx, col_idx, float(voorraad.loc[mask, col].values[0]))
    except Exception as e:
        st.error(f"Kon voorraad niet updaten: {e}")

# ------------------------------
# Record helpers
# ------------------------------
def add_record(record_type, values, rerun=False):
    if sheet_baby is None:
        st.error("Sheet niet beschikbaar")
        return False
    nieuwe_id = f"R{len(baby_records) + 1:03}"
    row = [nieuwe_id, record_type] + values
    try:
        sheet_baby.append_row(row)
        st.success(f"{record_type} toegevoegd")
        if rerun:
            st.rerun()
        return True
    except Exception as e:
        st.error(f"Kon niet toevoegen: {e}")
        return False

def add_activiteit(start_dt, end_dt, duur, activiteit_type, reactie, opm):
    if sheet_activiteiten is None:
        st.error("Activiteiten sheet niet beschikbaar")
        return False
    try:
        nieuwe_id = f"A{sheet_activiteiten.row_count:03}"
        row = [nieuwe_id, start_dt, end_dt, duur, activiteit_type, reactie, opm]
        sheet_activiteiten.append_row(row)
        return True
    except Exception as e:
        st.error(f"Kon activiteit niet opslaan: {e}")
        return False

def edit_record(row_index, updates, rerun=False):
    if sheet_baby is None:
        st.error("Sheet niet beschikbaar")
        return False
    try:
        for col, val in updates.items():
            sheet_baby.update_cell(row_index, col, val)
        st.success("Record aangepast")
        if rerun:
            st.rerun()
        return True
    except Exception as e:
        st.error(f"Kon niet updaten: {e}")
        return False

# ------------------------------
# Sidebar menu
# ------------------------------
TAB_NAMES = ["Dashboard", "Slaap", "Voeding", "Luiers", "Gezondheid", "Activiteiten", "Voorraad", "Analyse", "Data", "Bewerk records", "Instellingen"]
TAB_ICONS = ["house", "moon", "cup-straw", "droplet", "heart", "balloon", "cart", "graph-up", "table", "pencil", "gear"]

if "selected_tab" not in st.session_state:
    st.session_state.selected_tab = "Dashboard"

with st.sidebar:
    st.markdown("""
    <style>
    @media (prefers-color-scheme: dark) {
        .bubbel-wordmark { color: #ffffff !important; }
        .bubbel-subtitle { color: #aaaaaa !important; }
    }
    @media (prefers-color-scheme: light) {
        .bubbel-wordmark { color: #1a1a1a !important; }
        .bubbel-subtitle { color: #888888 !important; }
    }
    </style>
    <div style="padding: 24px 8px 16px 8px;">
        <span class="bubbel-wordmark" style="font-size: 28px; font-weight: 700; letter-spacing: -0.5px;">Bubbel</span><span style="font-size: 28px; font-weight: 700; color: #7a9e72;">.</span>
    </div>
    """, unsafe_allow_html=True)
    selected_from_menu = option_menu(
        menu_title=None,
        options=TAB_NAMES,
        icons=TAB_ICONS,
        menu_icon="cast",
        orientation="vertical",
        key="main_option_menu"
    )

if st.session_state.get("selected_tab") != selected_from_menu:
    st.session_state.selected_tab = selected_from_menu

selected_tab = st.session_state.selected_tab

# ------------------------------
# TAB: Dashboard
# ------------------------------
if selected_tab == "Dashboard":
    baby_naam = inst.get('baby_naam', 'Bubbel')
    vandaag = date.today()
    MAANDEN_NL = ['januari','februari','maart','april','mei','juni','juli','augustus','september','oktober','november','december']
    datum_str = f"{vandaag.day} {MAANDEN_NL[vandaag.month - 1]}"

    # --- Data ophalen ---
    slaap_df = baby_records[(baby_records['Type'] == 'Slaap') & (baby_records['Starttijd'].dt.date == vandaag)] if not baby_records.empty else pd.DataFrame()
    voeding_df = baby_records[(baby_records['Type'] == 'Voeding') & (baby_records['Starttijd'].dt.date == vandaag)] if not baby_records.empty else pd.DataFrame()
    luier_df = baby_records[(baby_records['Type'] == 'Luier') & (baby_records['Starttijd'].dt.date == vandaag)] if not baby_records.empty else pd.DataFrame()
    act_vandaag = activiteiten[activiteiten['Starttijd'].dt.date == vandaag] if not activiteiten.empty else pd.DataFrame()
    gez_df = baby_records[baby_records['Type'] == 'Gezondheid'] if not baby_records.empty else pd.DataFrame()

    # Slaap stats
    aantal_slaap = len(slaap_df)
    laatste_slaap = slaap_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M') if not slaap_df.empty else None
    totaal_slaap_min = 0
    if not slaap_df.empty and 'Eindtijd' in slaap_df.columns:
        slaap_df2 = slaap_df.copy()
        slaap_df2['Eindtijd'] = pd.to_datetime(slaap_df2['Eindtijd'], errors='coerce')
        slaap_df2['duur'] = (slaap_df2['Eindtijd'] - slaap_df2['Starttijd']).dt.total_seconds() / 60
        totaal_slaap_min = int(slaap_df2['duur'].fillna(0).sum())
    slaap_tag = f"{totaal_slaap_min // 60}u {totaal_slaap_min % 60}m totaal" if totaal_slaap_min > 0 else "–"

    # Voeding stats
    aantal_voeding = len(voeding_df)
    laatste_voeding = voeding_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M') if not voeding_df.empty else None
    totaal_ml = voeding_df['Hoeveelheid'].sum() if not voeding_df.empty else 0

    # Luier stats
    nat_count = len(luier_df[luier_df['Type Luier'] == 'Nat']) if not luier_df.empty else 0
    vuil_count = len(luier_df[luier_df['Type Luier'] == 'Vuil']) if not luier_df.empty else 0
    laatste_luier = luier_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M') if not luier_df.empty else None

    # Activiteiten stats
    aantal_act = len(act_vandaag)
    if not act_vandaag.empty:
        laatste_act_row = act_vandaag.sort_values('Starttijd', ascending=False).iloc[0]
        laatste_act_naam = laatste_act_row.get('Activiteit_type', '') if 'Activiteit_type' in laatste_act_row.index else ''
        laatste_act_tijd = laatste_act_row['Starttijd'].strftime('%H:%M')
    else:
        laatste_act_naam = '–'
        laatste_act_tijd = None

    # Gezondheid
    if not gez_df.empty:
        laatste_gez = gez_df.sort_values('Starttijd', ascending=False).iloc[0]
        gez_datum = laatste_gez['Starttijd'].strftime('%-d %b')
        try: gewicht = float(str(laatste_gez.get('Gewicht', 0)).replace(',', '.'))
        except: gewicht = 0.0
        try: lengte = float(str(laatste_gez.get('Lengte', 0)).replace(',', '.'))
        except: lengte = 0.0
        try: temp = float(str(laatste_gez.get('Temperatuur', 0)).replace(',', '.'))
        except: temp = 0.0
    else:
        gez_datum = gewicht = lengte = temp = None

    # Voorraad waarschuwingen
    voorraad_items_html = ""
    if not voorraad.empty:
        for _, r in voorraad.iterrows():
            act = pd.to_numeric(r.get('Actuele voorraad', 0), errors='coerce') or 0
            mn = pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0
            if mn > 0 and act <= mn * 1.2:
                p_naam = r.get('Productnaam', '')
                p_eenh = r.get('Eenheid', '')
                is_laag = act <= mn
                kleur = "#b42318" if is_laag else "#b54708"
                voorraad_items_html += f'<div style="font-size:12px;color:{kleur};margin-top:2px;">{p_naam} — nog {act:.0f} {p_eenh}</div>'

    # Timeline opbouwen uit alle records van vandaag
    timeline_items = []
    if not slaap_df.empty:
        for _, r in slaap_df.iterrows():
            timeline_items.append(("💤", r['Starttijd'], "Slaap gestart", "#e8f4fd"))
            if pd.notna(r.get('Eindtijd')) and r.get('Eindtijd') != '':
                eind = pd.to_datetime(r.get('Eindtijd'), errors='coerce')
                if pd.notna(eind):
                    timeline_items.append(("☀️", eind, "Wakker", "#fff9e6"))
    if not voeding_df.empty:
        for _, r in voeding_df.iterrows():
            hoev = r.get('Hoeveelheid', '')
            vtype = r.get('Voeding_type', '')
            label = f"{vtype} {hoev:.0f}ml" if hoev and float(hoev) > 0 else vtype
            timeline_items.append(("🍼", r['Starttijd'], label, "#f0fdf4"))
    if not luier_df.empty:
        for _, r in luier_df.iterrows():
            ltype = r.get('Type Luier', 'Luier')
            timeline_items.append(("🧷", r['Starttijd'], f"Luier {ltype.lower()}", "#fdf4ff"))
    if not act_vandaag.empty:
        for _, r in act_vandaag.iterrows():
            anaam = r.get('Activiteit_type', 'Activiteit') if 'Activiteit_type' in r.index else 'Activiteit'
            timeline_items.append(("🐛", r['Starttijd'], anaam, "#fff7ed"))

    timeline_items.sort(key=lambda x: x[1], reverse=True)

    timeline_html = ""
    for icon, tijd, label, bg in timeline_items:
        tijd_str = tijd.strftime('%H:%M') if pd.notna(tijd) else ''
        timeline_html += f"""
<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;position:relative;">
  <div style="width:28px;height:28px;border-radius:50%;background:{bg};display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0;">{icon}</div>
  <div style="flex:1;font-size:13px;font-weight:500;">{label}</div>
  <div style="font-size:11px;color:#bbb;white-space:nowrap;">{tijd_str}</div>
</div>"""

    # --- Render ---
    st.markdown(f"""
<style>
@media (max-width: 640px) {{
    .dash-grid {{ grid-template-columns: 1fr 1fr !important; }}
}}
</style>
<div style="margin-bottom:20px;">
  <div style="font-size:28px;font-weight:800;letter-spacing:-1px;line-height:1.1;">Bubbel<span style="color:#7a9e72;">.</span></div>
  <div style="font-size:13px;color:#aaa;margin-top:3px;">Dagoverzicht van {baby_naam} · {datum_str}</div>
</div>
""", unsafe_allow_html=True)

    # Voorraad banner
    if voorraad_items_html:
        st.markdown(f"""
<div style="background:#fef3f2;border:1px solid #fecdca;border-radius:14px;padding:12px 16px;margin-bottom:16px;display:flex;gap:10px;align-items:flex-start;">
  <span style="font-size:18px;">⚠️</span>
  <div>
    <div style="font-weight:700;font-size:13px;color:#b42318;margin-bottom:2px;">Lage voorraad</div>
    {voorraad_items_html}
  </div>
</div>""", unsafe_allow_html=True)

    # Kaarten 2x2
    k1, k2 = st.columns(2)
    k3, k4 = st.columns(2)

    def dash_kaart(col, icon, titel, getal, subtekst, tag_tekst, tag_bg, tag_kleur, laatste=None):
        laatste_html = f'<span style="font-size:11px;color:#bbb;">{laatste}</span>' if laatste else ''
        col.markdown(f"""
<div style="border:1.5px solid #efefef;border-radius:18px;padding:16px 18px;height:100%;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
    <div style="display:flex;align-items:center;gap:6px;">
      <span style="font-size:16px;">{icon}</span>
      <span style="font-weight:700;font-size:13px;">{titel}</span>
    </div>
    {laatste_html}
  </div>
  <div style="font-size:34px;font-weight:800;letter-spacing:-1px;line-height:1;margin:6px 0 2px;">{getal}</div>
  <div style="font-size:11px;color:#aaa;margin-bottom:10px;">{subtekst}</div>
  <span style="background:{tag_bg};color:{tag_kleur};font-size:11px;font-weight:700;padding:3px 8px;border-radius:99px;">{tag_tekst}</span>
</div>""", unsafe_allow_html=True)

    dash_kaart(k1, "💤", "Slaap",
               aantal_slaap, "slaapjes vandaag", slaap_tag,
               "#e8f4fd", "#1a6fa8",
               laatste=f"laatste {laatste_slaap}" if laatste_slaap else None)

    dash_kaart(k2, "🍼", "Voeding",
               aantal_voeding, "voedingen vandaag",
               f"{totaal_ml:.0f} ml totaal" if totaal_ml > 0 else "–",
               "#f0fdf4", "#166534",
               laatste=f"laatste {laatste_voeding}" if laatste_voeding else None)

    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)

    # Luiers kaart apart (twee getallen)
    k3.markdown(f"""
<div style="border:1.5px solid #efefef;border-radius:18px;padding:16px 18px;height:100%;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
    <div style="display:flex;align-items:center;gap:6px;">
      <span style="font-size:16px;">🧷</span>
      <span style="font-weight:700;font-size:13px;">Luiers</span>
    </div>
    <span style="font-size:11px;color:#bbb;">{"laatste " + laatste_luier if laatste_luier else ""}</span>
  </div>
  <div style="display:flex;gap:16px;margin:6px 0 2px;">
    <div>
      <div style="font-size:34px;font-weight:800;letter-spacing:-1px;line-height:1;">{nat_count}</div>
      <div style="font-size:11px;color:#aaa;">nat</div>
    </div>
    <div style="width:1px;background:#f0f0f0;margin:4px 0;"></div>
    <div>
      <div style="font-size:34px;font-weight:800;letter-spacing:-1px;line-height:1;">{vuil_count}</div>
      <div style="font-size:11px;color:#aaa;">vuil</div>
    </div>
  </div>
  <div style="margin-top:10px;">
    <span style="background:#fdf4ff;color:#7c3aed;font-size:11px;font-weight:700;padding:3px 8px;border-radius:99px;">{nat_count + vuil_count} totaal</span>
  </div>
</div>""", unsafe_allow_html=True)

    dash_kaart(k4, "🎈", "Activiteiten",
               aantal_act, "vandaag",
               laatste_act_naam if laatste_act_naam != '–' else "–",
               "#fff7ed", "#c2410c",
               laatste=f"{laatste_act_tijd}" if laatste_act_tijd else None)

    st.write("")

    # Gezondheidskaart
    if gez_datum:
        st.markdown(f"""
<div style="border:1.5px solid #efefef;border-radius:18px;padding:16px 18px;margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <div style="display:flex;align-items:center;gap:6px;">
      <span style="font-size:16px;">🩺</span>
      <span style="font-weight:700;font-size:13px;">Gezondheid</span>
    </div>
    <span style="font-size:11px;color:#bbb;">meting {gez_datum}</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
    <div>
      <div style="font-size:10px;color:#aaa;margin-bottom:2px;">Gewicht</div>
      <div style="font-weight:700;font-size:16px;">{gewicht:.1f} <span style="font-weight:400;font-size:11px;color:#aaa;">kg</span></div>
    </div>
    <div>
      <div style="font-size:10px;color:#aaa;margin-bottom:2px;">Lengte</div>
      <div style="font-weight:700;font-size:16px;">{lengte:.1f} <span style="font-weight:400;font-size:11px;color:#aaa;">cm</span></div>
    </div>
    <div>
      <div style="font-size:10px;color:#aaa;margin-bottom:2px;">Temp.</div>
      <div style="font-weight:700;font-size:16px;">{temp:.1f} <span style="font-weight:400;font-size:11px;color:#aaa;">°C</span></div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

    # Timeline
    if timeline_html:
        st.markdown(f"""
<div style="border:1.5px solid #efefef;border-radius:18px;padding:16px 18px;">
  <div style="font-weight:700;font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:14px;">Vandaag</div>
  {timeline_html}
</div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
<div style="border:1.5px solid #efefef;border-radius:18px;padding:16px 18px;color:#bbb;font-size:13px;text-align:center;">
  Nog geen activiteit geregistreerd vandaag
</div>""", unsafe_allow_html=True)



# ------------------------------
# TAB: Slaap
# ------------------------------
if selected_tab == "Slaap":
    st.title("💤 Slaap toevoegen")
    start_time = st.time_input("Starttijd")
    duration = st.number_input("Duur (minuten)", min_value=0, value=int(inst.get('slaap_default_duur', 60)))
    opm = st.text_input("Opmerking")
    if st.button("💾 Opslaan"):
        start_dt = get_device_datetime(start_time)
        end_dt = start_dt + timedelta(minutes=duration)
        add_record(
            "Slaap",
            [start_dt.strftime("%Y-%m-%d %H:%M"), end_dt.strftime("%Y-%m-%d %H:%M"), duration, opm, '', '', '', '', '', '', '', '', '', '']
        )

# ------------------------------
# TAB: Voeding
# ------------------------------
if selected_tab == "Voeding":
    st.title("🍼 Voeding toevoegen")

    voeding_types = ['Borst', 'Fles', 'Kolven', 'Hapje']
    voeding_default_idx = voeding_types.index(inst.get('voeding_default_type', 'Fles')) if inst.get('voeding_default_type', 'Fles') in voeding_types else 1
    voeding_type = st.selectbox("Type voeding", voeding_types, index=voeding_default_idx, key='voeding_type_manual')
    tijdstip = st.time_input('Tijdstip', datetime.now().time(), key='voeding_tijd_manual')

    borst = kolven = fles = hapje_type = ''
    hoeveelheid = 0

    match voeding_type:
        case 'Borst':
            borst = st.selectbox('Borst', ['Links', 'Rechts', 'Beide'], key='voeding_borst_manual')
        case 'Fles':
            fles_types = ['melk', 'kunstvoeding']
            fles_default_idx = fles_types.index(inst.get('voeding_default_flestype', 'kunstvoeding')) if inst.get('voeding_default_flestype', 'kunstvoeding') in fles_types else 1
            fles = st.selectbox('Type fles', fles_types, index=fles_default_idx, key='voeding_fles_manual')
            hoeveelheid = st.number_input('Hoeveelheid (ml)', min_value=0, value=int(inst.get('voeding_default_ml', 100)), key='voeding_hoeveelheid_fles')
        case 'Kolven':
            borst = st.selectbox('Borst', ['Links', 'Rechts', 'Beide'], key='voeding_borst_kolven')
            kolven = st.number_input('Hoeveelheid (ml)', min_value=0, value=int(inst.get('voeding_default_kolven_ml', 10)), key='voeding_kolven_manual')
        case 'Hapje':
            hapje_type = st.selectbox('Type hapje', ['groente', 'fruit', 'snack'], key='voeding_hapje_type')
            hoeveelheid = st.number_input('Hoeveelheid (gram)', min_value=0, value=int(inst.get('voeding_default_hapje_gram', 50)), key='voeding_hoeveelheid_hapje')

    opm = st.text_input('Opmerking', key=f'voeding_opm_{voeding_type.lower()}')

    if st.button("💾 Opslaan", key='voeding_opslaan_manual'):
        start_dt = get_device_datetime(tijdstip).strftime('%Y-%m-%d %H:%M')
        add_record(
            'Voeding',
            [start_dt, '', hoeveelheid if voeding_type != 'Kolven' else '', opm, '', borst, kolven, fles, voeding_type, hapje_type, '', '', ''],
            rerun=False
        )
        # Automatisch voorraad verlagen
        if voeding_type == 'Fles' and fles == 'kunstvoeding' and hoeveelheid > 0:
            gram_per_schep = float(inst.get('kunstvoeding_gram_per_schep', 4.4))
            # Standaard flesgroottes Héro: (ml eindvolume, scheppen)
            STANDAARD_FLESSEN = [(65, 2), (100, 3), (135, 4), (165, 5), (200, 6)]
            # Exacte match of dichtstbijzijnde erboven
            scheppen = next((s for eindvol, s in STANDAARD_FLESSEN if eindvol >= hoeveelheid), STANDAARD_FLESSEN[-1][1])
            gram = round(scheppen * gram_per_schep, 1)
            update_voorraad("Kunstvoeding", -gram)
            st.caption(f"🍼 {scheppen} scheppen = {gram}g kunstvoeding afgetrokken van voorraad")
        st.success("Voeding opgeslagen ✅")

# ------------------------------
# TAB: Luiers
# ------------------------------
if selected_tab == "Luiers":
    st.title("💧 Luiers toevoegen")
    tijdstip = st.time_input("Tijdstip")
    luier_types = ["Nat", "Vuil"]
    luier_default_idx = luier_types.index(inst.get('luier_default_type', 'Nat')) if inst.get('luier_default_type', 'Nat') in luier_types else 0
    typ = st.selectbox("Type luier", luier_types, index=luier_default_idx)
    opm = st.text_input("Opmerking")
    if st.button("💾 Opslaan"):
        start_dt = get_device_datetime(tijdstip)
        add_record("Luier", [start_dt.strftime("%Y-%m-%d %H:%M"), '', '', opm, typ, '', '', '', '', '', '', '', ''])
        update_voorraad("Luiers", -1)

# ------------------------------
# TAB: Gezondheid
# ------------------------------
if selected_tab == "Gezondheid":
    st.title("🩺 Gezondheid toevoegen")
    gewicht = st.number_input("Gewicht (kg)", min_value=0.0, step=0.1, value=float(inst.get('gezondheid_default_gewicht', 5.0)))
    lengte = st.number_input("Lengte (cm)", min_value=30.0, step=0.1, value=float(inst.get('gezondheid_default_lengte', 50.0)))
    temp = st.number_input("Temperatuur (°C)", min_value=30.0, max_value=45.0, step=0.1, value=float(inst.get('gezondheid_default_temp', 36.5)))
    opm = st.text_area("Opmerkingen / ziekten")
    if st.button("💾 Opslaan"):
        start_dt = now_device()
        add_record("Gezondheid", [start_dt.strftime("%Y-%m-%d %H:%M"), '', '', '', '', '', '', '', '', '', gewicht, lengte, temp, opm])

# ------------------------------
# TAB: Activiteiten
# ------------------------------
if selected_tab == "Activiteiten":
    st.title("🎈 Activiteiten toevoegen")

    ACTIVITEITEN = [
        ("🐛", "Tummy time"),
        ("🛁", "Bad"),
        ("🚿", "Douchen"),
        ("🚶", "Wandelen"),
        ("🏊", "Zwemmen"),
        ("👨‍👩‍👧", "Familie/vrienden"),
        ("🏥", "CJG/Dokter"),
        ("🧸", "Speelmat"),
        ("🧣", "Draagdoek"),
    ]

    REACTIE_LABELS = ["Boos", "Huilerig", "Neutraal", "Blij", "Heel blij"]

    # --- Activiteit via st.pills ---
    pill_opties = [f"{icon} {naam}" for icon, naam in ACTIVITEITEN]
    activiteit_pill = st.pills("Activiteit", pill_opties, key="act_pills")
    activiteit_naam = activiteit_pill.split(" ", 1)[1] if activiteit_pill else None

    # --- Tijdstip en duur ---
    col1, col2 = st.columns(2)
    with col1:
        tijdstip = st.time_input("Tijdstip", datetime.now().time(), key="act_tijd")
    with col2:
        duur = st.number_input("Duur (minuten)", min_value=0, value=int(inst.get('activiteit_default_duur', 15)), key="act_duur")

    # --- Reactie via st.feedback ---
    st.markdown("**Reactie baby**")
    reactie_idx = st.feedback("faces", key="act_feedback")
    reactie = REACTIE_LABELS[reactie_idx] if reactie_idx is not None else None

    opm = st.text_input("Opmerking", key="act_opm")

    if st.button("💾 Opslaan", key="act_opslaan"):
        if not activiteit_naam:
            st.warning("Kies eerst een activiteit")
        elif reactie_idx is None:
            st.warning("Geef een reactie aan")
        else:
            start_dt = get_device_datetime(tijdstip)
            end_dt = start_dt + timedelta(minutes=duur)
            succes = add_activiteit(
                start_dt.strftime("%Y-%m-%d %H:%M"),
                end_dt.strftime("%Y-%m-%d %H:%M"),
                duur, activiteit_naam, reactie, opm
            )
            if succes:
                st.success("Activiteit opgeslagen ✅")

# ------------------------------
# TAB: Voorraad
# ------------------------------
if selected_tab == "Voorraad":

    STANDAARD_FLESSEN = [(65, 2), (100, 3), (135, 4), (165, 5), (200, 6)]
    gram_per_schep = float(inst.get('kunstvoeding_gram_per_schep', 4.4))

    def bereken_stats(naam, eenheid, actueel):
        """Bereken per_dag en dagen_resterend op basis van verbruik afgelopen 7 dagen."""
        per_dag = None
        dagen_resterend = None
        history = []  # verbruik per dag laatste 7 dagen

        if naam == "Kunstvoeding" and not baby_records.empty:
            for d in range(6, -1, -1):
                dag = date.today() - timedelta(days=d)
                dag_df = baby_records[
                    (baby_records['Type'] == 'Voeding') &
                    (baby_records['Voeding_type'] == 'Fles') &
                    (baby_records['Fles'] == 'kunstvoeding') &
                    (baby_records['Starttijd'].dt.date == dag)
                ]
                gram_dag = sum(
                    next((s for ev, s in STANDAARD_FLESSEN if ev >= row['Hoeveelheid']), 6) * gram_per_schep
                    for _, row in dag_df.iterrows()
                ) if not dag_df.empty else 0
                history.append(round(gram_dag, 1))
            totaal = sum(history)
            if totaal > 0:
                per_dag = round(totaal / 7, 1)
                dagen_resterend = int(actueel / per_dag)

        elif naam == "Luiers" and not baby_records.empty:
            for d in range(6, -1, -1):
                dag = date.today() - timedelta(days=d)
                dag_df = baby_records[
                    (baby_records['Type'] == 'Luier') &
                    (baby_records['Starttijd'].dt.date == dag)
                ]
                history.append(len(dag_df))
            totaal = sum(history)
            if totaal > 0:
                per_dag = round(totaal / 7, 1)
                dagen_resterend = int(actueel / per_dag)

        return per_dag, dagen_resterend, history

    def log_bijvulling(productnaam, hoeveelheid):
        if sheet_bijvulling:
            try:
                sheet_bijvulling.append_row([datetime.now().strftime('%Y-%m-%d %H:%M'), productnaam, hoeveelheid])
            except Exception as e:
                st.error(f"Kon bijvulling niet loggen: {e}")

    st.title("🛒 Voorraad")
    st.caption("Gebaseerd op verbruik afgelopen 7 dagen")

    if voorraad.empty:
        st.info('Geen voorraaddata beschikbaar. Controleer je Google Sheet.')
    else:
        # --- Lage voorraad banner ---
        lage_voorraad_items = []
        for _, r in voorraad.iterrows():
            actueel = pd.to_numeric(r.get('Actuele voorraad', 0), errors='coerce') or 0
            minimum = pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0
            if minimum > 0 and actueel <= minimum:
                naam = r.get('Productnaam', 'Onbekend')
                eenheid = r.get('Eenheid', 'stuks')
                _, dagen_r, _ = bereken_stats(naam, eenheid, actueel)
                dagen_str = f", genoeg voor ±{dagen_r} dagen" if dagen_r is not None else ""
                lage_voorraad_items.append(f"**{naam}** — {actueel:.0f} {eenheid} resterend{dagen_str}")
        if lage_voorraad_items:
            st.error("⚠️ Lage voorraad: " + "  |  ".join(lage_voorraad_items))

        # --- Voorraadkaarten ---
        # Responsive wrapper: naast elkaar op desktop, onder elkaar op mobiel
        st.markdown("""
        <style>
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stVerticalBlockBorderWrapper"]) {
            display: flex;
            flex-wrap: wrap;
            gap: 0;
        }
        @media (max-width: 640px) {
            div[data-testid="stHorizontalBlock"]:has(div[data-testid="stVerticalBlockBorderWrapper"]) > div {
                width: 100% !important;
                flex: 0 0 100% !important;
                min-width: 100% !important;
            }
        }
        </style>
        """, unsafe_allow_html=True)

        kaart_cols = st.columns(len(voorraad))
        for i, (_, r) in enumerate(voorraad.iterrows()):
            naam = r.get('Productnaam', 'Onbekend')
            variant = r.get('Variant', '')
            eenheid = r.get('Eenheid', 'stuks')
            actueel = pd.to_numeric(r.get('Actuele voorraad', 0), errors='coerce') or 0
            minimum = pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0

            per_dag, dagen_resterend, history = bereken_stats(naam, eenheid, actueel)

            is_laag = minimum > 0 and actueel <= minimum
            is_waarschuwing = not is_laag and minimum > 0 and actueel <= minimum * 1.2

            if is_laag:
                status_label, dagen_color, bar_color = "🔴 Laag", "#e74c3c", "#e74c3c"
            elif is_waarschuwing:
                status_label, dagen_color, bar_color = "🟠 Let op", "#e67e22", "#e67e22"
            else:
                status_label, dagen_color, bar_color = "🟢 Voldoende", "#7a9e72", "#7a9e72"

            if minimum == 0:
                st.caption(f"⚠️ Geen minimum ingesteld voor {naam} — stel dit in je Voorraad sheet in voor statusbepaling.")

            # Mini staafgrafiek SVG
            bar_max = max(history) if history and max(history) > 0 else 1
            bar_w, bar_gap, svg_h = 6, 3, 28
            svg_w = len(history) * (bar_w + bar_gap) - bar_gap
            bars_svg = ""
            for j, v in enumerate(history):
                h = max(2, int((v / bar_max) * svg_h))
                x = j * (bar_w + bar_gap)
                fill = bar_color if j == len(history) - 1 else bar_color + "66"
                bars_svg += f'<rect x="{x}" y="{svg_h - h}" width="{bar_w}" height="{h}" rx="2" fill="{fill}"/>'

            icon = "🧷" if naam == "Luiers" else "🍼"
            label = f"{icon} {naam}" + (f" · {variant}" if variant else "")

            per_dag_str = f"{per_dag} {eenheid}" if per_dag is not None else "–"
            dagen_str = f"±{dagen_resterend} dagen" if dagen_resterend is not None else "–"

            with kaart_cols[i].container(border=True):
                # Header + status + grafiek in één HTML blok zodat uitlijning klopt op mobiel
                st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
  <div style="font-weight:700;font-size:15px;">{naam}{f' <span style="font-weight:400;color:#888;">· {variant}</span>' if variant else ''}</div>
  <div style="font-size:13px;white-space:nowrap;margin-left:8px;">{status_label}</div>
</div>
<div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:12px;">
  <div>
    <div style="font-size:11px;color:#888;margin-bottom:2px;">{eenheid} resterend</div>
    <div style="font-size:38px;font-weight:800;letter-spacing:-1px;line-height:1;">{actueel:.0f}</div>
  </div>
  <div style="text-align:right;">
    <div style="font-size:10px;color:#aaa;margin-bottom:4px;">7 dagen</div>
    <svg width="{svg_w}" height="{svg_h}">{bars_svg}</svg>
  </div>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
  <div>
    <div style="font-size:11px;color:#888;margin-bottom:2px;">Gemiddeld/dag</div>
    <div style="font-size:18px;font-weight:700;">{per_dag_str}</div>
  </div>
  <div>
    <div style="font-size:11px;color:#888;margin-bottom:2px;">Nog mee</div>
    <div style="font-size:18px;font-weight:700;color:{dagen_color};">{dagen_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)

        st.caption("Schatting gebaseerd op gemiddeld verbruik afgelopen 7 dagen")
        st.divider()

        # --- Bijvullen snelkeuze ---
        st.subheader("📥 Bijvullen")
        bijvul_cols = st.columns(len(voorraad))
        for i, (_, r) in enumerate(voorraad.iterrows()):
            naam = r.get('Productnaam', 'Onbekend')
            eenheid = r.get('Eenheid', 'stuks')
            if naam == "Kunstvoeding":
                snelkeuze_opties = [("1 pak (700g)", 700), ("2 pakken (1400g)", 1400), ("3 pakken (2100g)", 2100)]
            elif naam == "Luiers":
                snelkeuze_opties = [("Midi pak (48)", 48), ("Groot pak (108)", 108)]
            else:
                snelkeuze_opties = []
            bijvul_cols[i].markdown(f"**{naam}**")
            for j, (label, waarde) in enumerate(snelkeuze_opties):
                if bijvul_cols[i].button(f"+ {label}", key=f'bijvul_{naam}_{j}', use_container_width=True):
                    update_voorraad(naam, waarde)
                    log_bijvulling(naam, waarde)
                    st.toast(f"{naam} bijgevuld met {waarde} {eenheid} ✅")
                    st.cache_data.clear()
                    st.rerun()

        # --- Aangepaste hoeveelheid bijvullen ---
        st.divider()
        st.subheader("➕ Aangepast bijvullen")
        prod_namen = voorraad['Productnaam'].tolist()
        ac1, ac2, ac3 = st.columns([2, 2, 1])
        with ac1:
            prod_to_add = st.selectbox('Product', prod_namen, key='p_add', label_visibility='collapsed')
        with ac2:
            eenheid_add = voorraad.loc[voorraad['Productnaam'] == prod_to_add, 'Eenheid'].values[0]
            aantal_to_add = st.number_input(f'Hoeveelheid ({eenheid_add})', min_value=0.0, step=1.0, value=1.0, key='a_add', label_visibility='collapsed')
        with ac3:
            st.write("")
            if st.button('Toevoegen', key='add_stock', use_container_width=True):
                update_voorraad(prod_to_add, float(aantal_to_add))
                log_bijvulling(prod_to_add, aantal_to_add)
                st.toast(f'{prod_to_add} bijgevuld ✅')
                st.cache_data.clear()
                st.rerun()

        # --- Correctie ---
        st.divider()
        st.subheader("🔧 Voorraad corrigeren")
        st.caption("Gebruik dit als de werkelijke voorraad afwijkt van wat de app bijhoudt.")
        cc1, cc2, cc3 = st.columns([2, 2, 1])
        with cc1:
            prod_cor = st.selectbox('Product', prod_namen, key='p_cor', label_visibility='collapsed')
        with cc2:
            eenheid_cor = voorraad.loc[voorraad['Productnaam'] == prod_cor, 'Eenheid'].values[0]
            huidige_waarde = float(pd.to_numeric(voorraad.loc[voorraad['Productnaam'] == prod_cor, 'Actuele voorraad'].values[0], errors='coerce') or 0)
            nieuwe_waarde = st.number_input(f'Werkelijke waarde ({eenheid_cor})', min_value=0.0, step=1.0, value=huidige_waarde, key=f'v_cor_{prod_cor}', label_visibility='collapsed')
        with cc3:
            st.write("")
            if st.button('Opslaan', key='cor_stock', use_container_width=True):
                verschil = nieuwe_waarde - huidige_waarde
                update_voorraad(prod_cor, verschil)
                log_bijvulling(f"{prod_cor} (correctie)", verschil)
                st.toast(f'Voorraad {prod_cor} gecorrigeerd naar {nieuwe_waarde:.0f} {eenheid_cor} ✅')
                st.cache_data.clear()
                st.rerun()

        # --- Bijvulhistorie ---
        st.divider()
        if not bijvullingen.empty:
            with st.expander("📋 Bijvulhistorie"):
                bv_df = bijvullingen.copy()
                bv_df['Datum'] = pd.to_datetime(bv_df['Datum'], errors='coerce')
                bv_df = bv_df.dropna(subset=['Datum']).sort_values('Datum', ascending=False).head(20)
                for _, row in bv_df.iterrows():
                    datum_str = row['Datum'].strftime('%d %b %H:%M')
                    prod = row.get('Productnaam', '')
                    hoev = row.get('Hoeveelheid', '')
                    is_cor = '(correctie)' in str(prod)
                    kleur = "#888" if is_cor else "#7a9e72"
                    teken = "±" if is_cor else "+"
                    st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f5f5f5;">
  <span style="font-size:12px;color:#bbb;width:100px;">{datum_str}</span>
  <span style="font-size:13px;font-weight:600;flex:1;">{prod}</span>
  <span style="font-size:13px;font-weight:700;color:{kleur};">{teken}{hoev}</span>
</div>""", unsafe_allow_html=True)
        else:
            with st.expander("📋 Bijvulhistorie"):
                st.info("Nog geen bijvullingen geregistreerd.")



# ------------------------------
# TAB: Bewerk records
# ------------------------------
if selected_tab == "Bewerk records":
    st.title('✏️ Bewerk bestaand record')

    record_type = st.selectbox('Kies type record', ['Slaap', 'Voeding', 'Luier', 'Gezondheid', 'Activiteit'])

    if record_type == 'Activiteit':
        if activiteiten.empty:
            st.info('Geen activiteiten beschikbaar')
        else:
            act_options = activiteiten.sort_values('Starttijd', ascending=False)['Starttijd'].dt.strftime('%Y-%m-%d %H:%M').tolist()
            selected = st.selectbox('Selecteer activiteit', act_options)
            if selected:
                idx = activiteiten[activiteiten['Starttijd'].dt.strftime('%Y-%m-%d %H:%M') == selected].index[0]
                sheet_row = idx + 2
                record = activiteiten.loc[idx]
                st.write(record)

                ACTIVITEITEN_NAMEN = ["Tummy time", "Bad", "Douchen", "Wandelen", "Zwemmen", "Familie/vrienden", "CJG/Dokter", "Speelmat", "Draagdoek"]
                REACTIE_LABELS = ["Boos", "Huilerig", "Neutraal", "Blij", "Heel blij"]

                act_idx = ACTIVITEITEN_NAMEN.index((record['Activiteit_type'] if 'Activiteit_type' in record.index else 'Tummy time')) if (record['Activiteit_type'] if 'Activiteit_type' in record.index else None) in ACTIVITEITEN_NAMEN else 0
                activiteit_type = st.selectbox('Activiteit', ACTIVITEITEN_NAMEN, index=act_idx)

                col1, col2 = st.columns(2)
                with col1:
                    tijdstip = st.time_input('Tijdstip', record['Starttijd'].time())
                with col2:
                    duur = st.number_input('Duur (minuten)', min_value=0, value=int((record['Duur'] if 'Duur' in record.index else 15)))

                reactie_idx = REACTIE_LABELS.index((record['Reactie'] if 'Reactie' in record.index else 'Blij')) if (record['Reactie'] if 'Reactie' in record.index else None) in REACTIE_LABELS else 3
                reactie = st.selectbox('Reactie', REACTIE_LABELS, index=reactie_idx)
                opm = st.text_input('Opmerking', (record['Opmerking'] if 'Opmerking' in record.index else ''))

                if st.button('Opslaan wijziging activiteit'):
                    start_dt = get_device_datetime(tijdstip, record['Starttijd'].date())
                    end_dt = start_dt + timedelta(minutes=duur)
                    if sheet_activiteiten:
                        try:
                            sheet_activiteiten.update_cell(sheet_row, 2, start_dt.strftime('%Y-%m-%d %H:%M'))
                            sheet_activiteiten.update_cell(sheet_row, 3, end_dt.strftime('%Y-%m-%d %H:%M'))
                            sheet_activiteiten.update_cell(sheet_row, 4, duur)
                            sheet_activiteiten.update_cell(sheet_row, 5, activiteit_type)
                            sheet_activiteiten.update_cell(sheet_row, 6, reactie)
                            sheet_activiteiten.update_cell(sheet_row, 7, opm)
                            st.success('Activiteit aangepast ✅')
                        except Exception as e:
                            st.error(f"Kon niet updaten: {e}")
    else:
        df_type = baby_records[baby_records['Type'] == record_type].sort_values('Starttijd', ascending=False)

        if df_type.empty:
            st.info('Geen records beschikbaar')
        else:
            options = df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M').tolist()
            selected = st.selectbox('Selecteer record', options)
            if selected:
                idx = df_type[df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M') == selected].index[0]
                sheet_row = idx + 2
                record = df_type.loc[idx]
                st.write(record)

                if record_type == 'Slaap':
                    start = st.time_input('Starttijd', record['Starttijd'].time())
                    duur = st.number_input('Duur (min)', value=int((record['Hoeveelheid'] if 'Hoeveelheid' in record.index else 0)), min_value=0)
                    opm = st.text_input('Opmerking', (record['Opmerking'] if 'Opmerking' in record.index else ''))
                    if st.button('Opslaan wijziging slaap'):
                        start_dt = get_device_datetime(start)
                        eind_dt = start_dt + timedelta(minutes=duur)
                        edit_record(sheet_row, {3: start_dt.strftime('%Y-%m-%d %H:%M'), 4: eind_dt.strftime('%Y-%m-%d %H:%M'), 5: duur, 6: opm})

                elif record_type == 'Voeding':
                    start = st.time_input('Tijdstip', record['Starttijd'].time())
                    hoeveelheid = st.number_input('Hoeveelheid', value=int((record['Hoeveelheid'] if 'Hoeveelheid' in record.index else 0)), min_value=0)
                    opm = st.text_input('Opmerking', (record['Opmerking'] if 'Opmerking' in record.index else ''))
                    if st.button('Opslaan wijziging voeding'):
                        start_dt = get_device_datetime(start)
                        edit_record(sheet_row, {3: start_dt.strftime('%Y-%m-%d %H:%M'), 5: hoeveelheid, 6: opm})

                elif record_type == 'Luier':
                    start = st.time_input('Tijdstip', record['Starttijd'].time())
                    typ = st.selectbox('Type luier', ['Nat', 'Vuil'], index=['Nat', 'Vuil'].index((record['Type Luier'] if 'Type Luier' in record.index else 'Nat')))
                    opm = st.text_input('Opmerking', (record['Opmerking'] if 'Opmerking' in record.index else ''))
                    if st.button('Opslaan wijziging luier'):
                        start_dt = get_device_datetime(start)
                        edit_record(sheet_row, {3: start_dt.strftime('%Y-%m-%d %H:%M'), 6: opm, 7: typ})

                elif record_type == 'Gezondheid':
                    gewicht = st.number_input('Gewicht (kg)', value=float((record['Gewicht'] if 'Gewicht' in record.index else 0.0)), min_value=0.0)
                    lengte = st.number_input('Lengte (cm)', value=float((record['Lengte'] if 'Lengte' in record.index else 0.0)), min_value=0.0)
                    temp = st.number_input('Temperatuur (°C)', value=float((record['Temperatuur'] if 'Temperatuur' in record.index else 0.0)), min_value=0.0)
                    opm = st.text_area('Opmerkingen / ziekten', (record['Opmerkingen / ziekten'] if 'Opmerkingen / ziekten' in record.index else ''))
                    if st.button('Opslaan wijziging gezondheid'):
                        edit_record(sheet_row, {11: gewicht, 12: lengte, 13: temp, 14: opm})

# ------------------------------
# TAB: Analyse
# ------------------------------
if selected_tab == "Analyse":
    st.title("📊 Analyse trends")

    if baby_records.empty:
        st.info("Geen gegevens beschikbaar voor analyse.")
    else:
        voeding_df = baby_records[baby_records['Type'] == 'Voeding'].copy()
        if not voeding_df.empty:
            voeding_df['Datum'] = voeding_df['Starttijd'].dt.date
            voeding_plot_df = voeding_df[voeding_df['Voeding_type'].isin(['Borst', 'Fles'])].copy()

            daily_voeding = voeding_plot_df.groupby('Datum')['Hoeveelheid'].sum().reset_index()
            with st.expander("🍼 Dagelijkse voeding (ml)"):
                chart = alt.Chart(daily_voeding).mark_bar(color='lightblue').encode(
                    x='Datum:T', y='Hoeveelheid:Q', tooltip=['Datum', 'Hoeveelheid']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)

            def get_daypart(hour):
                if 6 <= hour < 12:
                    return 'Ochtend'
                elif 12 <= hour < 18:
                    return 'Middag'
                elif 18 <= hour < 24:
                    return 'Avond'
                else:
                    return 'Nacht'

            voeding_plot_df['Dagdeel'] = voeding_plot_df['Starttijd'].dt.hour.apply(get_daypart)
            avg_voeding = voeding_plot_df.groupby('Dagdeel')['Hoeveelheid'].mean().reset_index()
            with st.expander("🕓 Gemiddelde voeding per dagdeel"):
                chart = alt.Chart(avg_voeding).mark_bar(color='lightgreen').encode(
                    x='Dagdeel:N', y='Hoeveelheid:Q', tooltip=['Dagdeel', 'Hoeveelheid']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Geen voeding gegevens beschikbaar.")

        slaap_df = baby_records[baby_records['Type'] == 'Slaap'].copy()
        if not slaap_df.empty:
            slaap_df['Datum'] = slaap_df['Starttijd'].dt.date
            slaap_df['Eindtijd'] = pd.to_datetime(slaap_df['Eindtijd'], errors='coerce')
            slaap_df['Duur_min'] = ((slaap_df['Eindtijd'] - slaap_df['Starttijd']).dt.total_seconds() / 60).fillna(0)

            daily_slaap = slaap_df.groupby('Datum').size().reset_index(name='Aantal slaapjes')
            with st.expander("💤 Aantal slaapjes per dag"):
                chart = alt.Chart(daily_slaap).mark_line(point=True, color='orange').encode(
                    x='Datum:T', y='Aantal slaapjes:Q', tooltip=['Datum', 'Aantal slaapjes']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)

            daily_slaapduur = slaap_df.groupby('Datum')['Duur_min'].sum().reset_index()
            with st.expander("⏱️ Totale slaapduur per dag (minuten)"):
                chart = alt.Chart(daily_slaapduur).mark_line(point=True, color='purple').encode(
                    x='Datum:T', y='Duur_min:Q', tooltip=['Datum', 'Duur_min']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Geen slaapgegevens beschikbaar.")

        gewicht_df = baby_records[baby_records['Type'] == 'Gezondheid'].copy()
        if not gewicht_df.empty:
            gewicht_df['Datum'] = gewicht_df['Starttijd'].dt.date
            with st.expander("⚖️ Gewichtontwikkeling"):
                chart = alt.Chart(gewicht_df).mark_line(point=True, color='green').encode(
                    x='Datum:T', y='Gewicht:Q', tooltip=['Datum', 'Gewicht']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Geen gewicht gegevens beschikbaar.")

        luier_df = baby_records[baby_records['Type'] == 'Luier'].copy()

        with st.expander("📈 Afwijkingen / ratio's"):
            if not voeding_df.empty:
                borst_count = len(voeding_df[voeding_df['Voeding_type'] == 'Borst'])
                fles_count = len(voeding_df[voeding_df['Voeding_type'] == 'Fles'])
                totaal = borst_count + fles_count
                if totaal > 0:
                    st.write(f"Percentage borstvoeding: {borst_count / totaal * 100:.1f}%")
                    st.write(f"Percentage flesvoeding: {fles_count / totaal * 100:.1f}%")
            else:
                st.write("Geen voeding gegevens beschikbaar voor ratio's.")

            if not luier_df.empty:
                nat = len(luier_df[luier_df['Type Luier'] == 'Nat'])
                vuil = len(luier_df[luier_df['Type Luier'] == 'Vuil'])
                totaal_luiers = nat + vuil
                if totaal_luiers > 0:
                    st.write(f"Percentage natte luiers: {nat / totaal_luiers * 100:.1f}%")
                    st.write(f"Percentage vuile luiers: {vuil / totaal_luiers * 100:.1f}%")
            else:
                st.write("Geen luiergegevens beschikbaar voor ratio's.")

        if not activiteiten.empty:
            act_df = activiteiten.copy()
            act_df['Datum'] = act_df['Starttijd'].dt.date
            act_df['Uur'] = act_df['Starttijd'].dt.hour

            with st.expander("🏆 Meest gedane activiteiten"):
                counts = act_df.groupby('Activiteit_type').size().reset_index(name='Aantal')
                chart = alt.Chart(counts).mark_bar(color='#7a9e72').encode(
                    x=alt.X('Activiteit_type:N', title='Activiteit'),
                    y='Aantal:Q',
                    tooltip=['Activiteit_type', 'Aantal']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)

            with st.expander("🕐 Activiteiten per uur van de dag"):
                uur_counts = act_df.groupby('Uur').size().reset_index(name='Aantal')
                chart = alt.Chart(uur_counts).mark_bar(color='#e8956d').encode(
                    x='Uur:O', y='Aantal:Q', tooltip=['Uur', 'Aantal']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)

            with st.expander("😊 Reactie per type activiteit"):
                reactie_df = act_df.groupby(['Activiteit_type', 'Reactie']).size().reset_index(name='Aantal')
                chart = alt.Chart(reactie_df).mark_bar().encode(
                    x=alt.X('Activiteit_type:N', title='Activiteit'),
                    y='Aantal:Q',
                    color=alt.Color('Reactie:N', scale=alt.Scale(
                        domain=['Boos', 'Huilerig', 'Neutraal', 'Blij', 'Heel blij'],
                        range=['#d63031', '#e17055', '#b2bec3', '#00b894', '#00635a']
                    )),
                    tooltip=['Activiteit_type', 'Reactie', 'Aantal']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)

# ------------------------------
# TAB: Data
# ------------------------------
if selected_tab == "Data":
    st.title("📋 Overzicht babyrecords")
    datum_input = st.date_input("Selecteer periode", [datetime.now() - timedelta(days=7), datetime.now()])
    if isinstance(datum_input, (list, tuple)):
        start_date, end_date = datum_input
    else:
        start_date = end_date = datum_input

    df_period = baby_records[
        (baby_records['Starttijd'].dt.date >= start_date) &
        (baby_records['Starttijd'].dt.date <= end_date)
    ]
    if df_period.empty:
        st.info("Geen records beschikbaar")
    else:
        st.dataframe(df_period, use_container_width=True)
        csv = df_period.to_csv(index=False).encode('utf-8')
        st.download_button("Download CSV", csv, "records.csv", "text/csv")

# ------------------------------
# TAB: Instellingen
# ------------------------------
if selected_tab == "Instellingen":
    st.title("⚙️ Instellingen")

    st.subheader("👶 Baby")
    baby_naam = st.text_input("Naam baby", value=inst.get('baby_naam', 'Bubbel'))

    st.subheader("🍼 Voeding")
    voeding_types = ['Borst', 'Fles', 'Kolven', 'Hapje']
    voeding_default_type = st.selectbox(
        "Standaard type voeding", voeding_types,
        index=voeding_types.index(inst.get('voeding_default_type', 'Fles'))
    )
    fles_types = ['melk', 'kunstvoeding']
    voeding_default_flestype = st.selectbox(
        "Standaard flestype", fles_types,
        index=fles_types.index(inst.get('voeding_default_flestype', 'kunstvoeding'))
    )
    voeding_default_ml = st.number_input("Standaard hoeveelheid fles (ml)", min_value=0, value=int(inst.get('voeding_default_ml', 100)))
    voeding_default_kolven_ml = st.number_input("Standaard hoeveelheid kolven (ml)", min_value=0, value=int(inst.get('voeding_default_kolven_ml', 10)))
    voeding_default_hapje_gram = st.number_input("Standaard hoeveelheid hapje (gram)", min_value=0, value=int(inst.get('voeding_default_hapje_gram', 50)))
    kunstvoeding_gram_per_schep = st.number_input(
        "Gram poeder per schep kunstvoeding", min_value=0.1, step=0.1, value=float(inst.get('kunstvoeding_gram_per_schep', 4.4)),
        help="Héro: 4,4g per schep. Aptamil: 4,3g. Nutrilon: 4,5g."
    )

    st.subheader("💤 Slaap")
    slaap_default_duur = st.number_input("Standaard slaapduur (minuten)", min_value=0, value=int(inst.get('slaap_default_duur', 60)))

    st.subheader("💧 Luiers")
    luier_types = ['Nat', 'Vuil']
    luier_default_type = st.selectbox(
        "Standaard luiertype", luier_types,
        index=luier_types.index(inst.get('luier_default_type', 'Nat'))
    )

    st.subheader("🎈 Activiteiten")
    activiteit_default_duur = st.number_input("Standaard duur activiteit (minuten)", min_value=0, value=int(inst.get('activiteit_default_duur', 15)))

    st.subheader("🩺 Gezondheid")
    col1, col2, col3 = st.columns(3)
    with col1:
        gezondheid_default_gewicht = st.number_input("Standaard gewicht (kg)", min_value=0.0, step=0.1, value=float(inst.get('gezondheid_default_gewicht', 5.0)))
    with col2:
        gezondheid_default_lengte = st.number_input("Standaard lengte (cm)", min_value=0.0, step=0.1, value=float(inst.get('gezondheid_default_lengte', 50.0)))
    with col3:
        gezondheid_default_temp = st.number_input("Standaard temperatuur (°C)", min_value=30.0, max_value=45.0, step=0.1, value=float(inst.get('gezondheid_default_temp', 36.5)))

    if st.button("💾 Instellingen opslaan"):
        nieuw = {
            'baby_naam': baby_naam,
            'voeding_default_type': voeding_default_type,
            'voeding_default_flestype': voeding_default_flestype,
            'voeding_default_ml': voeding_default_ml,
            'voeding_default_kolven_ml': voeding_default_kolven_ml,
            'voeding_default_hapje_gram': voeding_default_hapje_gram,
            'kunstvoeding_gram_per_schep': kunstvoeding_gram_per_schep,
            'slaap_default_duur': slaap_default_duur,
            'luier_default_type': luier_default_type,
            'activiteit_default_duur': activiteit_default_duur,
            'gezondheid_default_gewicht': gezondheid_default_gewicht,
            'gezondheid_default_lengte': gezondheid_default_lengte,
            'gezondheid_default_temp': gezondheid_default_temp,
        }
        for sleutel, waarde in nieuw.items():
            save_instelling(sleutel, waarde)
        st.cache_data.clear()
        st.success("Instellingen opgeslagen ✅")
        st.rerun()