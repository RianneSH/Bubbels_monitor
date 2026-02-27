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
def update_voorraad(productnaam, hoeveelheid):
    if voorraad.empty or sheet_voorraad is None:
        st.warning("Voorraad niet beschikbaar")
        return
    mask = voorraad['Productnaam'] == productnaam
    if not mask.any():
        st.error("Product niet gevonden")
        return
    voorraad.loc[mask, 'Actuele voorraad'] = (
        pd.to_numeric(voorraad.loc[mask, 'Actuele voorraad'], errors='coerce').fillna(0) + hoeveelheid
    ).astype(int)
    voorraad.loc[voorraad['Actuele voorraad'] < 0, 'Actuele voorraad'] = 0
    row_idx = mask[mask].index[0] + 2
    col_idx = voorraad.columns.get_loc('Actuele voorraad') + 1
    try:
        sheet_voorraad.update_cell(row_idx, col_idx, int(voorraad.loc[mask, 'Actuele voorraad'].values[0]))
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
TAB_ICONS = ["house", "moon", "cup-straw", "droplet", "heart", "balloon", "box", "graph-up", "table", "pencil", "gear"]

if "selected_tab" not in st.session_state:
    st.session_state.selected_tab = "Dashboard"

with st.sidebar:
    st.markdown("""
    <div style="padding: 24px 8px 16px 8px;">
        <span style="font-size: 28px; font-weight: 700; letter-spacing: -0.5px; color: #1a1a1a;">Bubbel</span><span style="font-size: 28px; font-weight: 700; color: #7a9e72;">.</span>
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
    st.markdown(f"""
    <div style="padding: 8px 0 24px 0;">
        <div><span style="font-size: 36px; font-weight: 700; letter-spacing: -0.5px; color: #1a1a1a;">Bubbel</span><span style="font-size: 36px; font-weight: 700; color: #7a9e72;">.</span></div>
        <div style="font-size: 16px; color: #888; margin-top: 4px;">Dagoverzicht van {baby_naam}</div>
    </div>
    """, unsafe_allow_html=True)
    vandaag = date.today()

    col1, col2, col3, col4, col5 = st.columns(5)

    slaap_df = baby_records[(baby_records['Type'] == 'Slaap') & (baby_records['Starttijd'].dt.date == vandaag)]
    if not slaap_df.empty:
        aantal_slaap = len(slaap_df)
        laatste_slaap = slaap_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M')
        col1.metric("💤 Slaapjes vandaag", f"{aantal_slaap}", delta=f"Laatste: {laatste_slaap}")
    else:
        col1.metric("💤 Slaapjes vandaag", "0")

    voeding_df = baby_records[(baby_records['Type'] == 'Voeding') & (baby_records['Starttijd'].dt.date == vandaag)]
    if not voeding_df.empty:
        aantal_voeding = len(voeding_df)
        laatste_voeding = voeding_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M')
        totaal_ml = voeding_df['Hoeveelheid'].sum()
        col2.metric("🍼 Voedingen vandaag", f"{aantal_voeding}", delta=f"Laatste: {laatste_voeding}")
        col4.metric("💧 Totaal ml voeding vandaag", f"{totaal_ml:.1f} ml")
    else:
        col2.metric("🍼 Voedingen vandaag", "0")
        col4.metric("💧 Totaal ml voeding vandaag", "0 ml")

    luier_df = baby_records[(baby_records['Type'] == 'Luier') & (baby_records['Starttijd'].dt.date == vandaag)]
    if not luier_df.empty:
        nat_count = len(luier_df[luier_df['Type Luier'] == 'Nat'])
        vuil_count = len(luier_df[luier_df['Type Luier'] == 'Vuil'])
        col3.markdown(f"**🧷 Luiers vandaag**\n\nNat: {nat_count}  \nVuil: {vuil_count}")
    else:
        col3.markdown("**🧷 Luiers vandaag**\n\nNat: 0  \nVuil: 0")

    if not activiteiten.empty:
        act_vandaag = activiteiten[activiteiten['Starttijd'].dt.date == vandaag]
        aantal_act = len(act_vandaag)
        if aantal_act > 0:
            laatste_act = act_vandaag.sort_values('Starttijd', ascending=False).iloc[0]
            laatste_act_naam = laatste_act.get('Activiteit_type', '')
            laatste_act_tijd = laatste_act['Starttijd'].strftime('%H:%M')
            col5.metric("🎈 Activiteiten vandaag", f"{aantal_act}", delta=f"Laatste: {laatste_act_naam} {laatste_act_tijd}")
        else:
            col5.metric("🎈 Activiteiten vandaag", "0")
    else:
        col5.metric("🎈 Activiteiten vandaag", "0")

    gez_df = baby_records[baby_records['Type'] == 'Gezondheid']
    if not gez_df.empty:
        laatste_gez = gez_df.sort_values('Starttijd', ascending=False).iloc[0]
        tijd = laatste_gez['Starttijd'].strftime('%H:%M')
        try:
            gewicht = float(str(laatste_gez.get('Gewicht', 0)).replace(',', '.'))
        except:
            gewicht = 0.0
        try:
            lengte = float(str(laatste_gez.get('Lengte', 0)).replace(',', '.'))
        except:
            lengte = 0.0
        try:
            temp = float(str(laatste_gez.get('Temperatuur', 0)).replace(',', '.'))
        except:
            temp = 0.0
        opmerkingen = laatste_gez.get('Opmerkingen / ziekten', 'Geen')
        st.subheader("🩺 Laatste gezondheid record")
        st.markdown(f"""
        **Tijdstip:** {tijd}  
        **Gewicht:** {gewicht:.1f} kg  
        **Lengte:** {lengte:.1f} cm  
        **Temperatuur:** {temp:.1f} °C  
        **Opmerkingen:** {opmerkingen if opmerkingen else 'Geen'}
        """)
    else:
        st.subheader("🩺 Gezondheid")
        st.info("Geen gegevens beschikbaar")

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
    st.title("📦 Voorraad beheren")

    if voorraad.empty:
        st.info('Geen voorraaddata')
    else:
        st.subheader("Huidige voorraad")
        for _, r in voorraad.iterrows():
            try:
                val = int(pd.to_numeric(r.get('Actuele voorraad', 0), errors='coerce') or 0)
                minv = int(pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0)
            except Exception:
                val = 0
                minv = 0
            kleur = '🟢' if val > minv + 2 else ('🟠' if val > minv else '🔴')
            st.markdown(f"**{kleur} {r.get('Productnaam','Onbekend')}** — {val} (min {minv})")

    st.subheader('Bijvullen')
    prod_to_add = st.selectbox('Product', voorraad['Productnaam'].tolist() if not voorraad.empty else [], key='p_add')
    aantal_to_add = st.number_input('Aantal toevoegen', min_value=1, value=1, key='a_add')
    if st.button('Voorraad bijvullen', key='add_stock'):
        update_voorraad(prod_to_add, int(aantal_to_add))
        if sheet_bijvulling is not None:
            sheet_bijvulling.append_row([datetime.now().strftime('%Y-%m-%d %H:%M'), prod_to_add, int(aantal_to_add)])
        st.success('Voorraad bijgewerkt')

    st.subheader('Verwijderen')
    prod_to_remove = st.selectbox('Product', voorraad['Productnaam'].tolist() if not voorraad.empty else [], key='p_rem')
    try:
        maxv = int(pd.to_numeric(voorraad.loc[voorraad['Productnaam'] == prod_to_remove, 'Actuele voorraad'].values[0]) or 0)
    except Exception:
        maxv = 0
    aantal_to_remove = st.number_input('Aantal verwijderen', min_value=1, max_value=max(maxv, 1), value=1, key='a_rem')
    if st.button('Voorraad verminderen', key='rem_stock'):
        update_voorraad(prod_to_remove, -int(aantal_to_remove))
        st.success('Voorraad bijgewerkt')

# ------------------------------
# TAB: Bewerk records
# ------------------------------
if selected_tab == "Bewerk records":
    st.title('✏️ Bewerk bestaand record')

    record_type = st.selectbox('Kies type record', ['Slaap', 'Voeding', 'Luier', 'Gezondheid'])
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
                duur = st.number_input('Duur (min)', value=int(record.get('Hoeveelheid', 0)), min_value=0)
                opm = st.text_input('Opmerking', record.get('Opmerking', ''))
                if st.button('Opslaan wijziging slaap'):
                    start_dt = get_device_datetime(start)
                    eind_dt = start_dt + timedelta(minutes=duur)
                    edit_record(sheet_row, {3: start_dt.strftime('%Y-%m-%d %H:%M'), 4: eind_dt.strftime('%Y-%m-%d %H:%M'), 5: duur, 6: opm})

            elif record_type == 'Voeding':
                start = st.time_input('Tijdstip', record['Starttijd'].time())
                hoeveelheid = st.number_input('Hoeveelheid', value=int(record.get('Hoeveelheid', 0)), min_value=0)
                opm = st.text_input('Opmerking', record.get('Opmerking', ''))
                if st.button('Opslaan wijziging voeding'):
                    start_dt = get_device_datetime(start)
                    edit_record(sheet_row, {3: start_dt.strftime('%Y-%m-%d %H:%M'), 5: hoeveelheid, 6: opm})

            elif record_type == 'Luier':
                start = st.time_input('Tijdstip', record['Starttijd'].time())
                typ = st.selectbox('Type luier', ['Nat', 'Vuil'], index=['Nat', 'Vuil'].index(record.get('Type Luier', 'Nat')))
                opm = st.text_input('Opmerking', record.get('Opmerking', ''))
                if st.button('Opslaan wijziging luier'):
                    start_dt = get_device_datetime(start)
                    edit_record(sheet_row, {3: start_dt.strftime('%Y-%m-%d %H:%M'), 6: opm, 7: typ})

            elif record_type == 'Gezondheid':
                gewicht = st.number_input('Gewicht (kg)', value=float(record.get('Gewicht', 0.0)), min_value=0.0)
                lengte = st.number_input('Lengte (cm)', value=float(record.get('Lengte', 0.0)), min_value=0.0)
                temp = st.number_input('Temperatuur (°C)', value=float(record.get('Temperatuur', 0.0)), min_value=0.0)
                opm = st.text_area('Opmerkingen / ziekten', record.get('Opmerkingen / ziekten', ''))
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
                        range=['#c0392b', '#e74c3c', '#95a5a6', '#2ecc71', '#27ae60']
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