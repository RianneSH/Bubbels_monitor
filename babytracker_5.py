import os
import json
import gspread
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials

# ------------------------------
# Streamlit page config
# ------------------------------
st.set_page_config(
    page_title="Bubbel",
    page_icon="🫧",
    layout="wide"
)

# ------------------------------
# Google Sheets verbinding
# ------------------------------
scopes = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive"
]

creds = None
client = None

# Streamlit Cloud secret
json_creds = os.environ.get("GCP_SERVICE_ACCOUNT")
if json_creds:
    try:
        creds_dict = json.loads(json_creds)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
    except Exception as e:
        st.error(f"Kon de Google credentials niet laden: {e}")
else:
    if os.path.exists("credentials.json"):
        try:
            creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
            client = gspread.authorize(creds)
        except Exception as e:
            st.error(f"Kon credentials.json niet laden: {e}")
    else:
        st.warning("Geen Google credentials gevonden.")

sheet_baby = sheet_voorraad = sheet_bijvulling = None
if client:
    try:
        sheet_baby = client.open("BabyTracker").worksheet("BabyRecords")
        sheet_voorraad = client.open("BabyTracker").worksheet("Voorraad")
        sheet_bijvulling = client.open("BabyTracker").worksheet("VoorraadBijvulling")
    except Exception as e:
        st.error(f"Kan Google Sheets niet openen: {e}")

# ------------------------------
# Data ophalen met caching
# ------------------------------
@st.cache_data(ttl=60)  # cache 60 seconden
def load_data():
    baby_records = pd.DataFrame(sheet_baby.get_all_records()) if sheet_baby else pd.DataFrame()
    voorraad = pd.DataFrame(sheet_voorraad.get_all_records()) if sheet_voorraad else pd.DataFrame()
    bijvullingen = pd.DataFrame(sheet_bijvulling.get_all_records()) if sheet_bijvulling else pd.DataFrame()

    if not baby_records.empty:
        baby_records['Starttijd'] = pd.to_datetime(baby_records['Starttijd'])
        baby_records['Eindtijd'] = pd.to_datetime(baby_records['Eindtijd'], errors='coerce')
        baby_records['Hoeveelheid'] = pd.to_numeric(baby_records['Hoeveelheid'], errors='coerce').fillna(0)
    if not bijvullingen.empty:
        bijvullingen['Datum'] = pd.to_datetime(bijvullingen['Datum'])

    return baby_records, voorraad, bijvullingen

baby_records, voorraad, bijvullingen = load_data()

# ------------------------------
# Voorraad helpers
# ------------------------------
def update_voorraad(productnaam, hoeveelheid):
    if voorraad.empty or sheet_voorraad is None:
        st.warning("Voorraad is niet beschikbaar")
        return
    mask = voorraad['Productnaam'] == productnaam
    voorraad.loc[mask, 'Actuele voorraad'] += hoeveelheid
    row_index = mask[mask].index[0] + 2
    col_index = voorraad.columns.get_loc("Actuele voorraad") + 1
    nieuw_voorraad = int(voorraad.loc[mask, "Actuele voorraad"].values[0])
    sheet_voorraad.update_cell(row_index, col_index, nieuw_voorraad)

# ------------------------------
# Dashboard helpers
# ------------------------------
def dashboard_data():
    if baby_records.empty:
        return {}
    df_today = baby_records[baby_records['Starttijd'].dt.date == datetime.today().date()]
    
    laatste_slaap = df_today[df_today['Type']=="Slaap"].sort_values("Starttijd", ascending=False).head(5)
    laatste_voeding = df_today[df_today['Type']=="Voeding"].sort_values("Starttijd", ascending=False).head(5)
    laatste_luier = df_today[df_today['Type']=="Luier"].sort_values("Starttijd", ascending=False).head(5)
    laatste_gezondheid = df_today[df_today['Type']=="Gezondheid"].sort_values("Starttijd", ascending=False).head(5)
    
    laag_voorraad = voorraad[voorraad['Actuele voorraad'] <= voorraad['Minimum voorraad']]['Productnaam'].tolist() if not voorraad.empty else []

    return {
        "Laatste slaap": laatste_slaap,
        "Laatste voeding": laatste_voeding,
        "Laatste luier": laatste_luier,
        "Laatste gezondheid": laatste_gezondheid,
        "Actuele voorraad": dict(zip(voorraad['Productnaam'], voorraad['Actuele voorraad'])) if not voorraad.empty else {},
        "Laag voorraad": laag_voorraad
    }

def plot_weekly_graph(type_event):
    if baby_records.empty:
        st.info("Geen baby records beschikbaar.")
        return
    last_week = datetime.today() - timedelta(days=7)
    df_week = baby_records[(baby_records['Starttijd'] >= last_week) & (baby_records['Type']==type_event)]
    if df_week.empty:
        st.info(f"Geen {type_event} gegevens voor de laatste week.")
        return
    df_week['Hoeveelheid'] = pd.to_numeric(df_week['Hoeveelheid'], errors='coerce').fillna(0)
    summary = df_week.groupby(df_week['Starttijd'].dt.date)['Hoeveelheid'].sum()
    st.line_chart(summary)

# ------------------------------
# Tabs
# ------------------------------
tabs = st.tabs(["Dashboard", "Slaap", "Voeding", "Luiers", "Gezondheid", "Voorraad", "Bewerk records"])

# ------------------------------
# TAB: Dashboard
# ------------------------------
with tabs[0]:
    st.title("🫧 Bubbels monitor")
    data = dashboard_data()

    st.subheader("💤 Laatste slaap")
    slaap_df = data.get("Laatste slaap", pd.DataFrame())
    if not slaap_df.empty:
        if "Slaapkwaliteit" not in slaap_df.columns:
            slaap_df["Slaapkwaliteit"] = ""
        if "Type slaap" not in slaap_df.columns:
            slaap_df["Type slaap"] = ""
        st.dataframe(slaap_df[["Starttijd","Eindtijd","Hoeveelheid","Opmerking","Type slaap","Slaapkwaliteit"]])
    else:
        st.info("Geen slaaprecords vandaag.")

    st.subheader("🍼 Laatste voeding")
    voeding_df = data.get("Laatste voeding", pd.DataFrame())
    for col in ["Borst","Kolven","Verhouding"]:
        if col not in voeding_df.columns:
            voeding_df[col] = ""
    if not voeding_df.empty:
        st.dataframe(voeding_df[["Starttijd","Hoeveelheid","Borst","Kolven","Verhouding","Opmerking"]])
    else:
        st.info("Geen voedingsrecords vandaag.")

    st.subheader("💩 Laatste luiers")
    luier_df = data.get("Laatste luier", pd.DataFrame())
    if not luier_df.empty:
        if "Type" not in luier_df.columns:
            luier_df["Type"] = ""
        st.dataframe(luier_df[["Starttijd","Type","Opmerking"]])
    else:
        st.info("Geen luierreocrds vandaag.")

    st.subheader("🩺 Laatste gezondheid")
    gezondheid_df = data.get("Laatste gezondheid", pd.DataFrame())
    for col in ["Gewicht","Lengte","Temperatuur","Opmerkingen / ziekten"]:
        if col not in gezondheid_df.columns:
            gezondheid_df[col] = ""
    if not gezondheid_df.empty:
        st.dataframe(gezondheid_df[["Starttijd","Gewicht","Lengte","Temperatuur","Opmerkingen / ziekten"]])
    else:
        st.info("Geen gezondheidsrecords vandaag.")

    st.subheader("📊 Grafieken laatste 7 dagen")
    st.write("Slaap (minuten)")
    plot_weekly_graph("Slaap")
    st.write("Voeding (ml)")
    plot_weekly_graph("Voeding")
    st.write("Luiers")
    plot_weekly_graph("Luier")

    st.subheader("📦 Voorraad")
    for i, row in voorraad.iterrows():
        voorraad_val = row["Actuele voorraad"]
        min_val = row["Minimum voorraad"]
        product = row["Productnaam"]
        kleur = "🟢"
        if voorraad_val <= min_val:
            kleur = "🔴"
        elif voorraad_val <= min_val + 2:
            kleur = "🟠"
        st.write(f"{kleur} {product}: {voorraad_val} (Min {min_val})")
