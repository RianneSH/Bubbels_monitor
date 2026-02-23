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
st.set_page_config(page_title="Bubbel", page_icon="🫧", layout="wide")

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
# Helpers
# ------------------------------
def load_data():
    baby_records = pd.DataFrame(sheet_baby.get_all_records()) if sheet_baby else pd.DataFrame()
    voorraad = pd.DataFrame(sheet_voorraad.get_all_records()) if sheet_voorraad else pd.DataFrame()
    bijvullingen = pd.DataFrame(sheet_bijvulling.get_all_records()) if sheet_bijvulling else pd.DataFrame()

    def parse_numeric(df, field):
        if field in df.columns:
            df[field] = pd.to_numeric(df[field].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    
    if not baby_records.empty:
        for field in ['Hoeveelheid','Gewicht','Lengte','Temperatuur']:
            parse_numeric(baby_records, field)
        for col in ['Starttijd','Eindtijd']:
            if col in baby_records.columns:
                baby_records[col] = pd.to_datetime(baby_records[col], errors='coerce')
    
    if not bijvullingen.empty and 'Datum' in bijvullingen.columns:
        bijvullingen['Datum'] = pd.to_datetime(bijvullingen['Datum'], errors='coerce')

    return baby_records, voorraad, bijvullingen

baby_records, voorraad, bijvullingen = load_data()

# ------------------------------
# Centrale device tijd functie
# ------------------------------

def get_device_datetime(time_input: time, date_input: date = None):
    if date_input is None:
        date_input = date.today()  # GEEN datetime.now() meer!
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

# ------------------------------
# Sidebar menu
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
        key="main_option_menu"
    )

if st.session_state.get("selected_tab") != selected_from_menu:
    st.session_state.selected_tab = selected_from_menu

selected_tab = st.session_state.selected_tab

# ------------------------------
# TAB: Dashboard
# ------------------------------
if selected_tab == "Dashboard":
    st.title("Bubbels monitor")
    vandaag = datetime.now().date()

    col1, col2, col3, col4 = st.columns(4)

    # Slaapjes
    slaap_df = baby_records[(baby_records['Type']=='Slaap') & (baby_records['Starttijd'].dt.date==vandaag)]
    if not slaap_df.empty:
        aantal_slaap = len(slaap_df)
        laatste_slaap = slaap_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M')
        col1.metric("💤 Slaapjes vandaag", f"{aantal_slaap}", delta=f"Laatste: {laatste_slaap}")
    else:
        col1.metric("💤 Slaapjes vandaag", "0")

    # Voedingen
    voeding_df = baby_records[(baby_records['Type']=='Voeding') & (baby_records['Starttijd'].dt.date==vandaag)]
    if not voeding_df.empty:
        aantal_voeding = len(voeding_df)
        laatste_voeding = voeding_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M')
        totaal_ml = voeding_df['Hoeveelheid'].sum()
        col2.metric("🍼 Voedingen vandaag", f"{aantal_voeding}", delta=f"Laatste: {laatste_voeding}")
        col4.metric("💧 Totaal ml voeding vandaag", f"{totaal_ml:.1f} ml")
    else:
        col2.metric("🍼 Voedingen vandaag", "0")
        col4.metric("💧 Totaal ml voeding vandaag", "0 ml")

    # Luiers
    luier_df = baby_records[(baby_records['Type']=='Luier') & (baby_records['Starttijd'].dt.date==vandaag)]
    if not luier_df.empty:
        nat_count = len(luier_df[luier_df['Type Luier']=='Nat'])
        vuil_count = len(luier_df[luier_df['Type Luier']=='Vuil'])
        col3.markdown(f"**🧷 Luiers vandaag**\n\nNat: {nat_count}  \nVuil: {vuil_count}")
    else:
        col3.markdown("**🧷 Luiers vandaag**\n\nNat: 0  \nVuil: 0")

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
    start_time = st.time_input("Starttijd", now_device().time())
    duration = st.number_input("Duur (minuten)", min_value=0, value=60)
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
    tijdstip = st.time_input("Tijdstip", now_device().time())
    hoeveelheid = st.number_input("Hoeveelheid (ml)", min_value=0, value=100)
    voeding_type = st.selectbox("Type voeding", ["Borst","Fles","Kolven","Hapje"])
    opm = st.text_input("Opmerking")
    if st.button("💾 Opslaan voeding"):
        start_dt = get_device_datetime(tijdstip)
        add_record(
            "Voeding",
            [start_dt.strftime("%Y-%m-%d %H:%M"), '', hoeveelheid, opm, '', '', '', '', voeding_type, '', '', '', '']
        )

# ------------------------------
# TAB: Luiers
# ------------------------------
if selected_tab == "Luiers":
    st.title("💧 Luiers toevoegen")
    tijdstip = st.time_input("Tijdstip", now_device().time())
    typ = st.selectbox("Type luier", ["Nat","Vuil"])
    opm = st.text_input("Opmerking")
    if st.button("💾 Opslaan"):
        start_dt = get_device_datetime(tijdstip)
        add_record(
            "Luier",
            [start_dt.strftime("%Y-%m-%d %H:%M"), '', '', opm, typ, '', '', '', '', '', '', '', '']
        )
        update_voorraad("Luiers", -1)

# ------------------------------
# TAB: Gezondheid
# ------------------------------
if selected_tab == "Gezondheid":
    st.title("🩺 Gezondheid toevoegen")
    gewicht = st.number_input("Gewicht (kg)", min_value=0.0, step=0.1, value=5.0)
    lengte = st.number_input("Lengte (cm)", min_value=30.0, step=0.1, value=50.0)
    temp = st.number_input("Temperatuur (°C)", min_value=30.0, max_value=45.0, step=0.1, value=36.5)
    opm = st.text_area("Opmerkingen / ziekten")
    if st.button("💾 Opslaan"):
        start_dt = now_device()
        add_record(
            "Gezondheid",
            [start_dt.strftime("%Y-%m-%d %H:%M"), '', '', '', '', '', '', '', '', '', gewicht, lengte, temp, opm]
        )

# ------------------------------
# TAB: Bewerk records
# ------------------------------
if selected_tab == "Bewerk records":
    st.title('✏️ Bewerk bestaand record')
    
    record_type = st.selectbox('Kies type record', ['Slaap','Voeding','Luier','Gezondheid'])
    df_type = baby_records[baby_records['Type']==record_type].sort_values('Starttijd', ascending=False)
    
    if df_type.empty:
        st.info('Geen records beschikbaar')
    else:
        options = df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M').tolist()
        selected = st.selectbox('Selecteer record', options)
        if selected:
            idx = df_type[df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M')==selected].index[0]
            sheet_row = idx + 2
            record = df_type.loc[idx]
            st.write(record)

            # --- Afhankelijk van type renderen ---
            if record_type == 'Slaap':
                start = st.time_input('Starttijd', record['Starttijd'].time())
                duur = st.number_input('Duur (min)', int(record.get('Hoeveelheid',0)))
                opm = st.text_input('Opmerking', record.get('Opmerking',''))
                if st.button('Opslaan wijziging slaap'):
                    start_dt = get_device_datetime(start)
                    eind_dt = start_dt + timedelta(minutes=duur)
                    edit_record(sheet_row, {
                        3: start_dt.strftime('%Y-%m-%d %H:%M'),
                        4: eind_dt.strftime('%Y-%m-%d %H:%M'),
                        5: duur,
                        6: opm
                    })

            elif record_type == 'Voeding':
                start = st.time_input('Tijdstip', record['Starttijd'].time())
                hoeveelheid = st.number_input('Hoeveelheid', int(record.get('Hoeveelheid',0)))
                opm = st.text_input('Opmerking', record.get('Opmerking',''))
                if st.button('Opslaan wijziging voeding'):
                    start_dt = get_device_datetime(start)
                    edit_record(sheet_row, {
                        3: start_dt.strftime('%Y-%m-%d %H:%M'),
                        5: hoeveelheid,
                        6: opm
                    })

            elif record_type == 'Luier':
                start = st.time_input('Tijdstip', record['Starttijd'].time())
                typ = st.selectbox('Type luier', ['Nat','Vuil'], index=['Nat','Vuil'].index(record.get('Type Luier','Nat')))
                opm = st.text_input('Opmerking', record.get('Opmerking',''))
                if st.button('Opslaan wijziging luier'):
                    start_dt = get_device_datetime(start)
                    edit_record(sheet_row, {
                        3: start_dt.strftime('%Y-%m-%d %H:%M'),
                        6: opm,
                        7: typ
                    })

            elif record_type == 'Gezondheid':
                gewicht = st.number_input('Gewicht (kg)', float(record.get('Gewicht',0.0)))
                lengte = st.number_input('Lengte (cm)', float(record.get('Lengte',0.0)))
                temp = st.number_input('Temperatuur (°C)', float(record.get('Temperatuur',0.0)))
                opm = st.text_area('Opmerkingen / ziekten', record.get('Opmerkingen / ziekten',''))
                if st.button('Opslaan wijziging gezondheid'):
                    edit_record(sheet_row, {
                        11: gewicht,
                        12: lengte,
                        13: temp,
                        14: opm
                    })

# ------------------------------
# TAB: Analyse
# ------------------------------
if selected_tab == "Analyse":
    st.title("📊 Analyse trends")
    if baby_records.empty:
        st.info("Geen gegevens beschikbaar voor analyse.")
    else:
        # Dagelijkse voeding
        voeding_df = baby_records[baby_records['Type']=="Voeding"].copy()
        if not voeding_df.empty:
            voeding_df['Datum'] = voeding_df['Starttijd'].dt.date
            daily_voeding = voeding_df.groupby('Datum')['Hoeveelheid'].sum().reset_index()
            chart = alt.Chart(daily_voeding).mark_bar(color='lightblue').encode(
                x='Datum:T', y='Hoeveelheid:Q', tooltip=['Datum','Hoeveelheid']
            ).properties(height=250)
            st.altair_chart(chart, use_container_width=True)

        # Dagelijkse slaap
        slaap_df = baby_records[baby_records['Type']=="Slaap"].copy()
        if not slaap_df.empty:
            slaap_df['Datum'] = slaap_df['Starttijd'].dt.date
            slaap_df['Eindtijd'] = pd.to_datetime(slaap_df['Eindtijd'], errors='coerce')
            slaap_df['Duur_min'] = ((slaap_df['Eindtijd']-slaap_df['Starttijd']).dt.total_seconds()/60).fillna(0)
            daily_slaap = slaap_df.groupby('Datum')['Duur_min'].sum().reset_index()
            chart = alt.Chart(daily_slaap).mark_line(point=True, color='orange').encode(
                x='Datum:T', y='Duur_min:Q', tooltip=['Datum','Duur_min']
            ).properties(height=250)
            st.altair_chart(chart, use_container_width=True)

# ------------------------------
# TAB: Data
# ------------------------------
if selected_tab == "Data":
    st.title("📋 Overzicht babyrecords")
    datum_input = st.date_input("Selecteer periode", [datetime.now()-timedelta(days=7), datetime.now()])
    if isinstance(datum_input, (list,tuple)):
        start_date, end_date = datum_input
    else:
        start_date = end_date = datum_input

    df_period = baby_records[(baby_records['Starttijd'].dt.date>=start_date) & (baby_records['Starttijd'].dt.date<=end_date)]
    if df_period.empty:
        st.info("Geen records beschikbaar")
    else:
        st.dataframe(df_period, use_container_width=True)
        csv = df_period.to_csv(index=False).encode('utf-8')
        st.download_button("Download CSV", csv, "records.csv", "text/csv")