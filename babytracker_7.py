import os
import json
import gspread
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
import altair as alt
from streamlit_option_menu import option_menu
import time

# ------------------------------
# Config
# ------------------------------
st.set_page_config(page_title="Bubbel", page_icon="🫧", layout="wide")
LOCAL_TZ = 'Europe/Amsterdam'


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

sheet_baby = sheet_voorraad = sheet_bijvulling = None
if client:
    try:
        book = client.open("BabyTracker")
        sheet_baby = book.worksheet("BabyRecords")
        sheet_voorraad = book.worksheet("Voorraad")
        sheet_bijvulling = book.worksheet("VoorraadBijvulling")
    except Exception as e:
        st.error(f"Kan Google Sheets niet openen: {e}")

# ------------------------------
# Timer-functionaliteit
# ------------------------------
if 'active_session' not in st.session_state:
    st.session_state.active_session = None  # {'type': 'Voeding'/'Slaap', 'start_time': datetime}

@st.cache_data(ttl=3600, show_spinner=False)
def get_cached_session():
    """Ophalen van tijdelijk opgeslagen actieve sessie (werkt binnen zelfde device/browser)"""
    return st.session_state.active_session

def start_session(sessietype):
    if st.session_state.active_session:
        st.warning("Er loopt al een sessie! Stop die eerst voordat je een nieuwe start.")
        return
    st.session_state.active_session = {'type': sessietype, 'start_time': datetime.now()}
    st.toast(f"⏱️ {sessietype} gestart om {st.session_state.active_session['start_time'].strftime('%H:%M')}")

def stop_session():
    sessie = st.session_state.active_session
    if not sessie:
        st.warning("Er is geen actieve sessie om te stoppen.")
        return
    duur_min = (datetime.now() - sessie['start_time']).total_seconds() / 60
    st.toast(f"🛑 {sessie['type']} gestopt na {duur_min:.1f} minuten.")
    st.session_state.active_session = None
    return duur_min


# ------------------------------
# Helpers: load data with robust tz handling
# ------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def load_data():
    baby_records = pd.DataFrame(sheet_baby.get_all_records()) if sheet_baby else pd.DataFrame()
    voorraad = pd.DataFrame(sheet_voorraad.get_all_records()) if sheet_voorraad else pd.DataFrame()
    bijvullingen = pd.DataFrame(sheet_bijvulling.get_all_records()) if sheet_bijvulling else pd.DataFrame()

    def parse_time(val):
        if pd.isna(val) or val == '':
            return pd.NaT
        ts = pd.to_datetime(val, errors='coerce')
        if pd.isna(ts):
            return pd.NaT
        try:
            if ts.tzinfo is None:
                ts = ts.tz_localize(LOCAL_TZ)
            else:
                ts = ts.tz_convert(LOCAL_TZ)
        except Exception:
            ts = ts.tz_localize(LOCAL_TZ)
        return ts

    if not baby_records.empty:
        if 'Starttijd' in baby_records.columns:
            baby_records['Starttijd'] = baby_records['Starttijd'].apply(parse_time)
        if 'Eindtijd' in baby_records.columns:
            baby_records['Eindtijd'] = baby_records['Eindtijd'].apply(parse_time)
        
        # Velden die numeriek moeten zijn
        numeric_fields = ['Hoeveelheid','Gewicht','Lengte','Temperatuur']
        for field in numeric_fields:
            if field in baby_records.columns:
                # Vervang komma door punt en converteer naar float
                baby_records[field] = baby_records[field].astype(str).str.replace(',', '.')
                baby_records[field] = pd.to_numeric(baby_records[field], errors='coerce').fillna(0.0)

    if not bijvullingen.empty and 'Datum' in bijvullingen.columns:
        bijvullingen['Datum'] = bijvullingen['Datum'].apply(parse_time)

    return baby_records, voorraad, bijvullingen

# Data laden
baby_records, voorraad, bijvullingen = load_data()


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
            st.experimental_rerun()
        return True
    except Exception as e:
        st.error(f"Kon niet toevoegen: {e}")
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
            st.experimental_rerun()
        return True
    except Exception as e:
        st.error(f"Kon niet updaten: {e}")
        return False

#------------------------------
# Sidebar menu met optie-menu
# ------------------------------
TAB_NAMES = ["Dashboard","Slaap","Voeding","Luiers","Gezondheid","Voorraad","Analyse", "Data", "Bewerk records"]
TAB_ICONS = ["house", "moon", "cup-straw", "droplet", "heart", "box", "graph-up", "table", "pencil"]

if "selected_tab" not in st.session_state:
    st.session_state.selected_tab = "Dashboard"

with st.sidebar:
    selected_from_menu = option_menu(
        menu_title="☰ Menu",
        options=TAB_NAMES,
        icons=TAB_ICONS,
        menu_icon="cast",
        orientation="vertical",
        key="main_option_menu"  # belangrijk: persistente widget-key
    )

if st.session_state.get("selected_tab") != selected_from_menu:
    st.session_state.selected_tab = selected_from_menu

selected_tab = st.session_state.selected_tab

# ------------------------------
# TAB: Dashboard
# ------------------------------
if selected_tab == "Dashboard":
    st.title("Bubbels monitor")

    # ------------------------------
    # Voorraad-alert banner
    # ------------------------------

    def format_productlijst(producten):
        if not producten:
            return ""
        if len(producten) == 1:
            return producten[0]
        else:
            return ", ".join(producten[:-1]) + " en " + producten[-1]

    if not voorraad.empty:
        kritiek = voorraad[pd.to_numeric(voorraad['Actuele voorraad'], errors='coerce') <= 
                        pd.to_numeric(voorraad['Minimum voorraad'], errors='coerce')]
        if not kritiek.empty:
            product_lijst = format_productlijst(kritiek['Productnaam'].tolist())
            st.warning(f"⚠️ Lage voorraad! {product_lijst} zijn bijna op.")


    st.subheader("Overzicht laatste records van vandaag")
 
    # Huidige datum
    vandaag = pd.Timestamp(datetime.now().date())

    # Maak vier kolommen voor metrics
    col1, col2, col3, col4 = st.columns(4)

    # ------------------------------
    # Slaap - aantal en laatste tijd vandaag
    # ------------------------------
    slaap_df = baby_records[(baby_records['Type'] == 'Slaap') & 
                            (baby_records['Starttijd'].dt.date == vandaag.date())]
    if not slaap_df.empty:
        aantal_slaap = len(slaap_df)
        laatste_slaap = slaap_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M')
        col1.metric("💤 Slaapjes vandaag", f"{aantal_slaap}", delta=f"Laatste: {laatste_slaap}")
    else:
        col1.metric("💤 Slaapjes vandaag", "0")

    # ------------------------------
    # Voeding - aantal, laatste tijd en totaal ml vandaag (zonder kolven)
    # ------------------------------
    voeding_df = baby_records[
        (baby_records['Type'] == 'Voeding') &
        (baby_records['Starttijd'].dt.date == vandaag.date()) &
        (baby_records['Voeding_type'].isin(['Borst', 'Fles']))
    ]

    if not voeding_df.empty:
        aantal_voeding = len(voeding_df)
        laatste_voeding = voeding_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M')
        totaal_ml = voeding_df['Hoeveelheid'].sum()
        col2.metric("🍼 Voedingen vandaag", f"{aantal_voeding}", delta=f"Laatste: {laatste_voeding}")
        col4.metric("💧 Totaal ml voeding vandaag", f"{totaal_ml:.1f} ml")
    else:
        col2.metric("🍼 Voedingen vandaag", "0")
        col4.metric("💧 Totaal ml voeding vandaag", "0 ml")

    # ------------------------------
    # Luiers - aantal en laatste tijd vandaag
    # ------------------------------
    luier_df = baby_records[(baby_records['Type'] == 'Luier') & 
                            (baby_records['Starttijd'].dt.date == vandaag.date())]
    if not luier_df.empty:
        aantal_luier = len(luier_df)
        laatste_luier = luier_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M')
        col3.metric("🧷 Luiers vandaag", f"{aantal_luier}", delta=f"Laatste: {laatste_luier}")
    else:
        col3.metric("🧷 Luiers vandaag", "0")

    # ------------------------------
    # Gezondheid - laatste record (onafhankelijk van datum)
    # ------------------------------
    gez_df = baby_records[baby_records['Type'] == 'Gezondheid']
    if not gez_df.empty:
        laatste_gez = gez_df.sort_values('Starttijd', ascending=False).iloc[0]
        tijd = laatste_gez['Starttijd'].strftime('%H:%M')

        # Converteer waarden naar float, vervang komma door punt
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

    # Init session state
    if "active_slaap_session" not in st.session_state:
        st.session_state.active_slaap_session = None
    if "slaap_opmerking" not in st.session_state:
        st.session_state.slaap_opmerking = ""

    # Callback functies
    def start_slaap_callback():
        if st.session_state.active_slaap_session is None:
            st.session_state.active_slaap_session = {"start_time": datetime.now()}
            st.toast(f"⏱️ Slaap gestart om {st.session_state.active_slaap_session['start_time'].strftime('%H:%M')}")

    def stop_slaap_callback():
        sessie = st.session_state.active_slaap_session
        if not sessie:
            st.warning("Geen actieve sessie om te stoppen.")
            return
        duur_min = (datetime.now() - sessie["start_time"]).total_seconds() / 60
        eind_dt = datetime.now().strftime('%Y-%m-%d %H:%M')
        start_dt = sessie["start_time"].strftime('%Y-%m-%d %H:%M')
        opm = st.session_state.slaap_opmerking

        # Sla record op
        add_record(
            "Slaap",
            [
                start_dt,  # Starttijd
                eind_dt,   # Eindtijd
                round(duur_min),  # Hoeveelheid
                opm,       # Opmerking
                '', '', '', '', '', '', '', '', '', ''
            ],
            rerun=False
        )
        st.toast(f"🛑 Slaap gestopt na {duur_min:.1f} minuten")
        st.session_state.active_slaap_session = None
        st.session_state.slaap_opmerking = ""

    # Opmerkingen veld
    st.session_state.slaap_opmerking = st.text_input("Opmerking", st.session_state.slaap_opmerking, key="s_opm")

    # Timer UI
    if st.session_state.active_slaap_session:
        sessie = st.session_state.active_slaap_session
        # Bereken tijdsverschil
        elapsed = datetime.now() - sessie["start_time"]
        minuten, seconden = divmod(int(elapsed.total_seconds()), 60)
        st.info(f"Slaap bezig sinds {sessie['start_time'].strftime('%H:%M')} — ⏱️ {minuten}m {seconden}s")
        st.button("Stop slaap", on_click=stop_slaap_callback)
    else:
        st.button("▶️ Start slaap", on_click=start_slaap_callback)

    # Handmatig toevoegen alleen tonen als er geen actieve sessie is
    if not st.session_state.active_slaap_session:
        st.markdown("---")
        st.subheader("Handmatig slaap toevoegen")
        start_manual = st.time_input("Starttijd handmatig", datetime.now().time(), key='s_start')
        duur_manual = st.number_input("Duur (min)", min_value=0, value=60, key='s_duur')
        opm_manual = st.text_input("Opmerking", key='s_opm_manual')
        if st.button("Handmatig opslaan", key='s_opslaan'):
            start_dt = datetime.combine(datetime.today(), start_manual).strftime('%Y-%m-%d %H:%M')
            eind_dt = (datetime.combine(datetime.today(), start_manual) + timedelta(minutes=duur_manual)).strftime('%Y-%m-%d %H:%M')
            add_record(
                "Slaap",
                [
                    start_dt,  # Starttijd
                    eind_dt,   # Eindtijd
                    duur_manual,  # Hoeveelheid
                    opm_manual,   # Opmerking
                    '', '', '', '', '', '', '', '', '', ''
                ],
                rerun=False
            )
# ------------------------------
# TAB: Voeding 
# ------------------------------
if selected_tab == "Voeding":
    st.title("🍼 Voeding toevoegen")

    # ------------------------------
    # Timerfunctionaliteit
    # ------------------------------
    if 'active_voeding_session' not in st.session_state:
        st.session_state.active_voeding_session = None
    if 'voeding_opmerking' not in st.session_state:
        st.session_state.voeding_opmerking = ""

    def start_voeding(borstzijde):
        if st.session_state.active_voeding_session:
            st.warning("Er loopt al een sessie! Stop die eerst voordat je een nieuwe start.")
            return
        st.session_state.active_voeding_session = {
            'start_time': datetime.now(),
            'borst': borstzijde
        }
        st.toast(f"⏱️ Borstvoeding gestart om {st.session_state.active_voeding_session['start_time'].strftime('%H:%M')}")

    def stop_voeding():
        sessie = st.session_state.active_voeding_session
        if not sessie:
            st.warning("Er is geen actieve sessie om te stoppen.")
            return
        duur_min = (datetime.now() - sessie['start_time']).total_seconds() / 60
        eind_dt = datetime.now().strftime('%Y-%m-%d %H:%M')
        start_dt = sessie['start_time'].strftime('%Y-%m-%d %H:%M')
        opm = st.session_state.voeding_opmerking

        # Sla record op
        add_record(
            'Voeding',
            [
                start_dt,  # Starttijd
                eind_dt,   # Eindtijd
                '',        # Hoeveelheid (borstvoeding)
                opm,
                '',        # Type Luier
                sessie['borst'],  # Borstzijde
                '', '',            # Kolven/Fles
                'Borst',           # Type voeding
                '', '', '', '', 
            ],
            rerun=False
        )
        st.toast(f"🛑 Borstvoeding gestopt na {duur_min:.1f} minuten")
        st.session_state.active_voeding_session = None
        st.session_state.voeding_opmerking = ""

    # ------------------------------
    # Sectie 1: Live borstvoeding
    # ------------------------------
    st.subheader("⏱️ Live borstvoeding")
    st.session_state.voeding_opmerking = st.text_input("Opmerking", st.session_state.voeding_opmerking, key="voeding_opm_live")

    active = st.session_state.active_voeding_session
    if active:
        elapsed = datetime.now() - active['start_time']
        minuten, seconden = divmod(int(elapsed.total_seconds()), 60)
        st.info(f"Borstvoeding loopt sinds {active['start_time'].strftime('%H:%M')} — ⏱️ {minuten}m {seconden}s")
        st.button("🛑 Stop voeding", on_click=stop_voeding)
    else:
        borstzijde = st.selectbox('Borstzijde', ['Links', 'Rechts', 'Beide'], key='voeding_borst_zijde')
        st.button("▶️ Start borstvoeding", on_click=lambda: start_voeding(borstzijde))

    st.divider()

    # ------------------------------
    # Sectie 2: Handmatige invoer (Fles / Kolven / Borstvoeding)
    # ------------------------------
    if not st.session_state.active_voeding_session:
        st.subheader("🧾 Voeding handmatig registreren")
        voeding_type = st.selectbox("Type voeding", ['Borst', 'Fles', 'Kolven'], key='voeding_type_manual')
        tijdstip = st.time_input('Tijdstip', datetime.now().time(), key='voeding_tijd_manual')

        borst, kolven, fles, hoeveelheid, opm = '', '', '', 0, ''

        if voeding_type == 'Borst':
            borst = st.selectbox('Borst', ['Links', 'Rechts', 'Beide'], key='voeding_borst_manual')
            opm = st.text_input('Opmerking', key='voeding_opm_manual')
        elif voeding_type == 'Fles':
            fles = st.selectbox('Type fles', ['melk', 'kunstvoeding'], key='voeding_fles_manual')
            hoeveelheid = st.number_input('Hoeveelheid (ml)', min_value=0, value=50, key='voeding_hoeveelheid_manual')
            opm = st.text_input('Opmerking', key='voeding_opm_manual')
        elif voeding_type == 'Kolven':
            borst = st.selectbox('Borst', ['Links', 'Rechts', 'Beide'], key='voeding_borst_kolven')
            kolven = st.number_input('Hoeveelheid (ml)', min_value=0, value=10, key='voeding_kolven_manual')
            opm = st.text_input('Opmerking', key='voeding_opm_kolven')

        if st.button("💾 Handmatig opslaan", key='voeding_opslaan_manual'):
            start_dt = datetime.combine(datetime.today(), tijdstip).strftime('%Y-%m-%d %H:%M')
            add_record(
                'Voeding',
                [
                    start_dt,
                    '',  # Eindtijd
                    hoeveelheid if voeding_type != 'Kolven' else '',
                    opm,
                    '',
                    borst,
                    kolven,
                    fles,
                    voeding_type,
                    '', '', '', '',
                ],
                rerun=False
            )
            st.success("Voeding opgeslagen ✅")


# ------------------------------
# TAB: Luiers
# ------------------------------
if selected_tab == "Luiers":
    st.title("💧 Luiers toevoegen")
    
    tijdstip = st.time_input('Tijdstip', datetime.now().time(), key='l_start')
    typ = st.selectbox('Type luier', ['Nat', 'Vuil'], key='l_type')
    opm = st.text_input("Opmerking", key='l_opm')
    
    if st.button("Opslaan luier", key='l_opslaan'):
        start_dt = datetime.combine(datetime.today(), tijdstip).strftime('%Y-%m-%d %H:%M')
        
        success = add_record(
            "Luier",
            [
                start_dt,   # Starttijd
                '',         # Eindtijd
                '',         # Hoeveelheid
                opm,        # Opmerking
                typ,        # Type Luier
                '',         # Borst
                '',         # Kolven
                '',         # Fles
                '',         # Voeding_type
                '',         # Gewicht
                '',         # Lengte
                '',         # Temperatuur
                '',         # Opmerkingen / ziekten
            ],
            rerun=False
        )

    
        if success:
            update_voorraad("Luiers", -1)

# ------------------------------
# TAB: Gezondheid
# ------------------------------
if selected_tab == "Gezondheid":
    st.title("🩺 Gezondheid toevoegen")

    # Standaardwaarden en invoer
    gewicht = st.number_input('Gewicht (kg)', min_value=0.0, step=0.1, value=3.3, key='g_gewicht')
    lengte = st.number_input('Lengte (cm)', min_value=30.0, step=0.1, value=50.0, key='g_lengte')
    temp = st.number_input('Temperatuur (°C)', min_value=30.0, max_value=45.0, step=0.1, value=36.5, key='g_temp')
    opm = st.text_area('Opmerkingen / ziekten', key='g_opm')

    if st.button("Opslaan gezondheid", key='g_opslaan'):
        start_dt = datetime.now().strftime('%Y-%m-%d %H:%M')

        # Zorg dat komma's correct worden verwerkt
        gewicht = float(str(gewicht).replace(',', '.'))
        lengte = float(str(lengte).replace(',', '.'))
        temp = float(str(temp).replace(',', '.'))

        add_record(
            "Gezondheid",
            [
                start_dt,   # Starttijd
                '',         # Eindtijd
                '',         # Hoeveelheid
                '',         # Opmerking
                '', '', '', '',  # Type Luier, Borst, Kolven, Fles
                '',          # Voeding_type
                gewicht, # Gewicht 
                lengte,  # Lengte 
                temp,    # Temperatuur
                opm          # Opmerkingen / ziekten
            ],
            rerun=False
        )
# ------------------------------
# TAB: Voorraad
# ------------------------------
if selected_tab == "Voorraad":
    st.title("📦 Voorraad beheren")

    if voorraad.empty:
        st.info('Geen voorraaddata')
    else:
        st.subheader("Huidige voorraad")
        # Toon alle producten met kleurcode
        for _, r in voorraad.iterrows():
            try:
                val = int(pd.to_numeric(r.get('Actuele voorraad', 0), errors='coerce') or 0)
                minv = int(pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0)
            except Exception:
                val = 0
                minv = 0
            kleur = '🟢' if val > minv + 2 else ('🟠' if val > minv else '🔴')
            st.markdown(f"**{kleur} {r.get('Productnaam','Onbekend')}** — {val} (min {minv})")


    # ------------------------------
    # Bijvullen
    # ------------------------------
    st.subheader('Bijvullen')
    prod_to_add = st.selectbox('Product', voorraad['Productnaam'].tolist() if not voorraad.empty else [], key='p_add')
    aantal_to_add = st.number_input('Aantal toevoegen', min_value=1, value=1, key='a_add')
    if st.button('Voorraad bijvullen', key='add_stock'):
        update_voorraad(prod_to_add, int(aantal_to_add))
        if sheet_bijvulling is not None:
            sheet_bijvulling.append_row([datetime.now().strftime('%Y-%m-%d %H:%M'), prod_to_add, int(aantal_to_add)])
        st.success('Voorraad bijgewerkt')

    # ------------------------------
    # Verwijderen
    # ------------------------------
    st.subheader('Verwijderen')
    prod_to_remove = st.selectbox('Product', voorraad['Productnaam'].tolist() if not voorraad.empty else [], key='p_rem')
    try:
        maxv = int(pd.to_numeric(voorraad.loc[voorraad['Productnaam'] == prod_to_remove, 'Actuele voorraad'].values[0]) or 0)
    except Exception:
        maxv = 0
    aantal_to_remove = st.number_input('Aantal verwijderen', min_value=1, max_value=max(maxv,1), value=1, key='a_rem')
    if st.button('Voorraad verminderen', key='rem_stock'):
        update_voorraad(prod_to_remove, -int(aantal_to_remove))
        st.success('Voorraad bijgewerkt')


# ------------------------------
# TAB: Bewerk records
# ------------------------------
if selected_tab == "Bewerk records":
    st.title('✏️ Bewerk bestaand record')
    record_type = st.selectbox('Kies type record', ['Slaap','Voeding','Luier','Gezondheid'], key='edit_type')
    df_type = baby_records[baby_records['Type']==record_type].sort_values('Starttijd', ascending=False)
    if df_type.empty:
        st.info('Geen records beschikbaar')
    else:
        options = df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M').tolist()
        selected = st.selectbox('Selecteer record', options, key='edit_select')
        if selected:
            idx = df_type[df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M')==selected].index[0]
            sheet_row = idx + 2
            record = df_type.loc[idx]
            st.write(record)
            # Render editable fields depending on type
            if record_type == 'Slaap':
                start = st.time_input('Starttijd', record['Starttijd'].time(), key='e_s_start')
                duur = st.number_input('Duur (min)', int(record.get('Hoeveelheid',0)), key='e_s_duur')
                opm = st.text_input('Opmerking', record.get('Opmerking',''), key='e_s_opm')
                if st.button('Opslaan wijziging slaap', key='e_s_save'):
                    start_dt = datetime.combine(datetime.today(), start).strftime('%Y-%m-%d %H:%M')
                    edit_record(sheet_row, {3: start_dt, 4: (datetime.combine(datetime.today(), start) + timedelta(minutes=duur)).strftime('%Y-%m-%d %H:%M'), 5: duur, 6: opm})
            elif record_type == 'Voeding':
                start = st.time_input('Tijdstip', record['Starttijd'].time(), key='e_v_start')
                hoeveelheid = st.number_input('Hoeveelheid (ml)', int(record.get('Hoeveelheid',0)), key='e_v_how')
                borst = st.text_input('Borst', record.get('Borst',''), key='e_v_borst')
                kolven = st.text_input('Kolven', record.get('Kolven',''), key='e_v_kol')
                fles = st.text_input('Fles', record.get('Fles',''), key='e_v_fles')
                opm = st.text_input('Opmerking', record.get('Opmerking',''), key='e_v_opm')
                if st.button('Opslaan wijziging voeding', key='e_v_save'):
                    start_dt = datetime.combine(datetime.today(), start).strftime('%Y-%m-%d %H:%M')
                    edit_record(sheet_row, {3: start_dt, 5: hoeveelheid, 7: borst, 8: kolven, 9: fles, 6: opm})
            elif record_type == 'Luier':
                start = st.time_input('Tijdstip', record['Starttijd'].time(), key='e_l_start')
                typ = st.selectbox('Type luier', ['Plas','Poep','Beiden'], index=['Plas','Poep','Beiden'].index(record.get('Type Luier','Plas')), key='e_l_type')
                opm = st.text_input('Opmerking', record.get('Opmerking',''), key='e_l_opm')
                if st.button('Opslaan wijziging luier', key='e_l_save'):
                    start_dt = datetime.combine(datetime.today(), start).strftime('%Y-%m-%d %H:%M')
                    edit_record(sheet_row, {3: start_dt, 6: opm, 7: typ})
            elif record_type == 'Gezondheid':
                gewicht = st.number_input('Gewicht (kg)', float(record.get('Gewicht',0.0)), key='e_g_gewicht')
                lengte = st.number_input('Lengte (cm)', float(record.get('Lengte',0.0)), key='e_g_lengte')
                temp = st.number_input('Temperatuur (°C)', float(record.get('Temperatuur',0.0)), key='e_g_temp')
                opm = st.text_area('Opmerkingen / ziekten', record.get('Opmerkingen / ziekten',''), key='e_g_opm')
                if st.button('Opslaan wijziging gezondheid', key='e_g_save'):
                    edit_record(sheet_row, {6: gewicht, 7: lengte, 8: temp, 9: opm})

# ------------------------------
# TAB: Analyse
# ------------------------------
if selected_tab == "Analyse":
    st.title("📊 Analyse trends")
    
    if baby_records.empty:
        st.info("Geen gegevens beschikbaar voor analyse.")
    else:
        # ------------------------------
        # Voedingstrends
        # ------------------------------
        voeding_df = baby_records[baby_records['Type'] == 'Voeding'].copy()
        if not voeding_df.empty:
            voeding_df['Datum'] = voeding_df['Starttijd'].dt.date
            voeding_plot_df = voeding_df[voeding_df['Voeding_type'].isin(['Borst','Fles'])]

            # Dagelijkse totale voeding
            daily_voeding = voeding_plot_df.groupby('Datum')['Hoeveelheid'].sum().reset_index()
            with st.expander("🍼 Dagelijkse voeding (ml)"):
                chart = alt.Chart(daily_voeding).mark_bar(color='lightblue').encode(
                    x='Datum:T',
                    y='Hoeveelheid:Q',
                    tooltip=['Datum', 'Hoeveelheid']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)

            # Gemiddelde voeding per dagdeel
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
                    x='Dagdeel:N',
                    y='Hoeveelheid:Q',
                    tooltip=['Dagdeel', 'Hoeveelheid']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Geen voeding gegevens beschikbaar.")

        # ------------------------------
        # Slaaptrends
        # ------------------------------
        slaap_df = baby_records[baby_records['Type'] == 'Slaap'].copy()
        if not slaap_df.empty:
            slaap_df['Datum'] = slaap_df['Starttijd'].dt.date
            slaap_df['Eindtijd'] = pd.to_datetime(slaap_df['Eindtijd'], errors='coerce')
            slaap_df['Duur_min'] = ((slaap_df['Eindtijd'] - slaap_df['Starttijd']).dt.total_seconds() / 60).fillna(0)

            # Aantal slaapjes per dag
            daily_slaap = slaap_df.groupby('Datum').size().reset_index(name='Aantal slaapjes')
            with st.expander("💤 Aantal slaapjes per dag"):
                chart = alt.Chart(daily_slaap).mark_line(point=True, color='orange').encode(
                    x='Datum:T',
                    y='Aantal slaapjes:Q',
                    tooltip=['Datum', 'Aantal slaapjes']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)

            # Totale slaapduur per dag
            daily_slaapduur = slaap_df.groupby('Datum')['Duur_min'].sum().reset_index()
            with st.expander("⏱️ Totale slaapduur per dag (minuten)"):
                chart = alt.Chart(daily_slaapduur).mark_line(point=True, color='purple').encode(
                    x='Datum:T',
                    y='Duur_min:Q',
                    tooltip=['Datum', 'Duur_min']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Geen slaapgegevens beschikbaar.")

        # ------------------------------
        # Gewichtstrends
        # ------------------------------
        gewicht_df = baby_records[baby_records['Type'] == 'Gezondheid'].copy()
        if not gewicht_df.empty:
            gewicht_df['Datum'] = gewicht_df['Starttijd'].dt.date
            with st.expander("⚖️ Gewichtontwikkeling"):
                chart = alt.Chart(gewicht_df).mark_line(point=True, color='green').encode(
                    x='Datum:T',
                    y='Gewicht:Q',
                    tooltip=['Datum', 'Gewicht']
                ).properties(height=250)
                st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Geen gewicht gegevens beschikbaar.")

        # ------------------------------
        # Overige trends of afwijkingen (optioneel)
        # ------------------------------
        luier_df = baby_records[baby_records['Type'] == 'Luier'].copy()  # <--- toevoegen

        with st.expander("📈 Afwijkingen / ratio's"):
            # Borst vs flesvoeding
            if not voeding_df.empty:
                borst_count = len(voeding_df[voeding_df['Voeding_type']=='Borst'])
                fles_count = len(voeding_df[voeding_df['Voeding_type']=='Fles'])
                totaal = borst_count + fles_count
                st.write(f"Percentage borstvoeding: {borst_count/totaal*100:.1f}%")
                st.write(f"Percentage flesvoeding: {fles_count/totaal*100:.1f}%")
            else:
                st.write("Geen voeding gegevens beschikbaar voor ratio's.")

            # Nat vs vuil luiers
            if not luier_df.empty:
                nat = len(luier_df[luier_df['Type Luier']=='Nat'])
                vuil = len(luier_df[luier_df['Type Luier']=='Vuil'])
                totaal_luiers = nat + vuil
                st.write(f"Percentage natte luiers: {nat/totaal_luiers*100:.1f}%")
                st.write(f"Percentage vuile luiers: {vuil/totaal_luiers*100:.1f}%")
            else:
                st.write("Geen luiergegevens beschikbaar voor ratio's.")



# ------------------------------
# TAB: Data
# ------------------------------
if selected_tab == "Data":
    st.title("📋 Overzicht babyrecords")
    st.markdown("Kies een periode of één dag om een overzicht te krijgen voor kraamzorg.")

    # Periode selectie (ondersteunt één dag of range)
    datum_input = st.date_input(
        "Selecteer periode of dag",
        [datetime.now() - timedelta(days=7), datetime.now()]
    )

    # Ondersteuning voor enkele dag of range
    if isinstance(datum_input, list) or isinstance(datum_input, tuple):
        start_date, end_date = datum_input
    else:
        start_date = end_date = datum_input

    if start_date > end_date:
        st.error("Startdatum mag niet na einddatum zijn.")
    else:
        # Filter records in geselecteerde periode
        df_period = baby_records[
            (baby_records['Starttijd'].dt.date >= start_date) &
            (baby_records['Starttijd'].dt.date <= end_date)
        ]

        if df_period.empty:
            st.info("Geen records beschikbaar in deze periode.")
        else:
            # Check of het een enkele dag is
            enkele_dag = (start_date == end_date)

            if enkele_dag:
                st.subheader(f"Individuele records voor {start_date}")
                for record_type in ['Voeding','Slaap','Luier','Gezondheid']:
                    type_df = df_period[df_period['Type'] == record_type].copy()
                    if not type_df.empty:
                        with st.expander(f"{record_type} - individuele records"):
                            st.dataframe(type_df, use_container_width=True)
                            csv = type_df.to_csv(index=False).encode('utf-8')
                            st.download_button(
                                label=f"Download {record_type} CSV",
                                data=csv,
                                file_name=f"{record_type.lower()}_records.csv",
                                mime='text/csv'
                            )
            else:
                st.subheader(f"Samenvatting van {start_date} t/m {end_date}")

                # ------------------------------
                # Voeding overzicht
                # ------------------------------
                voeding_df = df_period[df_period['Type'] == 'Voeding'].copy()
                if not voeding_df.empty:
                    voeding_df['Datum'] = voeding_df['Starttijd'].dt.date
                    daily_voeding = voeding_df.groupby('Datum').agg(
                        aantal_voeding=('Type','count'),
                        totaal_ml=('Hoeveelheid','sum')
                    ).reset_index()

                    with st.expander("🍼 Voeding samenvatting"):
                        st.dataframe(daily_voeding, use_container_width=True)
                        csv = daily_voeding.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="Download voeding CSV",
                            data=csv,
                            file_name='voeding_overzicht.csv',
                            mime='text/csv'
                        )

                # ------------------------------
                # Slaap overzicht
                # ------------------------------
                slaap_df = df_period[df_period['Type'] == 'Slaap'].copy()
                if not slaap_df.empty:
                    slaap_df['Eindtijd'] = pd.to_datetime(slaap_df['Eindtijd'], errors='coerce')
                    slaap_df['Duur_min'] = ((slaap_df['Eindtijd'] - slaap_df['Starttijd']).dt.total_seconds() / 60).fillna(0)
                    slaap_df['Datum'] = slaap_df['Starttijd'].dt.date

                    daily_slaap = slaap_df.groupby('Datum').agg(
                        aantal_slaapjes=('Type','count'),
                        totaal_minuten=('Duur_min','sum')
                    ).reset_index()

                    with st.expander("💤 Slaap samenvatting"):
                        st.dataframe(daily_slaap, use_container_width=True)
                        csv = daily_slaap.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="Download slaap CSV",
                            data=csv,
                            file_name='slaap_overzicht.csv',
                            mime='text/csv'
                        )

                # ------------------------------
                # Luiers overzicht
                # ------------------------------
                luiers_df = df_period[df_period['Type'] == 'Luier'].copy()
                if not luiers_df.empty:
                    luiers_df['Datum'] = luiers_df['Starttijd'].dt.date
                    daily_luiers = luiers_df.groupby(['Datum','Type Luier']).size().unstack(fill_value=0).reset_index()

                    with st.expander("🧷 Luiers samenvatting"):
                        st.dataframe(daily_luiers, use_container_width=True)
                        csv = daily_luiers.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="Download luiers CSV",
                            data=csv,
                            file_name='luiers_overzicht.csv',
                            mime='text/csv'
                        )

                # ------------------------------
                # Gezondheid overzicht
                # ------------------------------
                gez_df = df_period[df_period['Type'] == 'Gezondheid'].copy()
                if not gez_df.empty:
                    gez_df['Datum'] = gez_df['Starttijd'].dt.date
                    daily_gez = gez_df.groupby('Datum').agg(
                        gewicht=('Gewicht','last'),
                        lengte=('Lengte','last'),
                        temperatuur=('Temperatuur','last'),
                        opmerkingen=('Opmerkingen / ziekten','last')
                    ).reset_index()

                    with st.expander("🩺 Gezondheid samenvatting"):
                        st.dataframe(daily_gez, use_container_width=True)
                        csv = daily_gez.to_csv(index=False).encode('utf-8')
                        st.download_button(
                            label="Download gezondheid CSV",
                            data=csv,
                            file_name='gezondheid_overzicht.csv',
                            mime='text/csv'
                        )


# Footer note
st.caption('Eigendom van J.M Severin')
