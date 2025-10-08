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
        creds_dict = json.loads(json_creds)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
    except Exception as e:
        st.error(f"Kon de Google credentials niet laden: {e}")
else:
    if os.path.exists("credentials.json"):
        try:
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
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

LOCAL_TZ = "Europe/Amsterdam"

# ------------------------------
# Data ophalen met caching
# ------------------------------
@st.cache_data(ttl=60)
def load_data():
    baby_records = pd.DataFrame(sheet_baby.get_all_records()) if sheet_baby else pd.DataFrame()
    voorraad = pd.DataFrame(sheet_voorraad.get_all_records()) if sheet_voorraad else pd.DataFrame()
    bijvullingen = pd.DataFrame(sheet_bijvulling.get_all_records()) if sheet_bijvulling else pd.DataFrame()

    if not baby_records.empty:
        baby_records['Starttijd'] = pd.to_datetime(baby_records['Starttijd']).dt.tz_localize('UTC').dt.tz_convert(LOCAL_TZ)
        baby_records['Eindtijd'] = pd.to_datetime(baby_records['Eindtijd'], errors='coerce').dt.tz_localize('UTC').dt.tz_convert(LOCAL_TZ)
        baby_records['Hoeveelheid'] = pd.to_numeric(baby_records['Hoeveelheid'], errors='coerce').fillna(0)
    if not bijvullingen.empty:
        bijvullingen['Datum'] = pd.to_datetime(bijvullingen['Datum']).dt.tz_localize('UTC').dt.tz_convert(LOCAL_TZ)

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
    today = pd.Timestamp(datetime.now(), tz=LOCAL_TZ).normalize()
    df_today = baby_records[baby_records['Starttijd'].dt.normalize() == today]

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
    last_week = pd.Timestamp(datetime.now(), tz=LOCAL_TZ) - pd.Timedelta(days=7)
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
    st.dataframe(slaap_df[["Starttijd","Eindtijd","Hoeveelheid","Opmerking"]] if not slaap_df.empty else pd.DataFrame())

    st.subheader("🍼 Laatste voeding")
    voeding_df = data.get("Laatste voeding", pd.DataFrame())
    st.dataframe(voeding_df[["Starttijd","Hoeveelheid","Borst","Kolven","Verhouding","Opmerking"]] if not voeding_df.empty else pd.DataFrame())

    st.subheader("💩 Laatste luiers")
    luier_df = data.get("Laatste luier", pd.DataFrame())
    st.dataframe(luier_df[["Starttijd","Type","Opmerking"]] if not luier_df.empty else pd.DataFrame())

    st.subheader("🩺 Laatste gezondheid")
    gezondheid_df = data.get("Laatste gezondheid", pd.DataFrame())
    st.dataframe(gezondheid_df[["Starttijd","Gewicht","Lengte","Temperatuur","Opmerkingen / ziekten"]] if not gezondheid_df.empty else pd.DataFrame())

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
        kleur = "🟢" if voorraad_val > min_val + 2 else "🟠" if voorraad_val > min_val else "🔴"
        st.write(f"{kleur} {product}: {voorraad_val} (Min {min_val})")

# ------------------------------
# TAB: Slaap toevoegen
# ------------------------------
with tabs[1]:
    st.title("💤 Slaap toevoegen")
    col1, col2 = st.columns(2)
    with col1:
        starttijd = st.time_input("Starttijd", datetime.now().time(), key="slaap_start")
    with col2:
        duur = st.number_input("Duur (minuten)", min_value=1, key="slaap_duur")
    opmerking = st.text_input("Opmerking", key="slaap_opmerking")

    if st.button("Opslaan slaap", key="slaap_btn"):
        nieuwe_id = f"R{len(baby_records)+1:03}"
        start_dt = pd.Timestamp(datetime.combine(datetime.today(), starttijd), tz=LOCAL_TZ)
        sheet_baby.append_row([nieuwe_id,"Slaap",start_dt.strftime("%Y-%m-%d %H:%M"),
                               (start_dt + pd.Timedelta(minutes=duur)).strftime("%Y-%m-%d %H:%M"),
                               duur, opmerking])
        st.success("Slaapje toegevoegd!")

# ------------------------------
# TAB: Voeding toevoegen
# ------------------------------
with tabs[2]:
    st.title("🍼 Voeding toevoegen")
    col1, col2 = st.columns(2)
    with col1:
        borst = st.selectbox("Borst/Fles", ["Links","Rechts","Beide","Fles"], key="voeding_borst")
        ml = st.number_input("Hoeveelheid (ml)", min_value=1, key="voeding_ml")
    with col2:
        kolven = st.radio("Kolven?", ["Ja","Nee"], key="voeding_kolven")
        tijdstip = st.time_input("Tijdstip", datetime.now().time(), key="voeding_tijd")
    verhouding = st.text_input("Fles/borst verhouding", key="voeding_verhouding")

    if st.button("Opslaan voeding", key="voeding_btn"):
        nieuwe_id = f"R{len(baby_records)+1:03}"
        start_dt = pd.Timestamp(datetime.combine(datetime.today(), tijdstip), tz=LOCAL_TZ)
        sheet_baby.append_row([nieuwe_id,"Voeding",start_dt.strftime("%Y-%m-%d %H:%M"),"",
                               ml,"",borst,kolven,verhouding])
        st.success("Voeding toegevoegd!")

# ------------------------------
# TAB: Luiers toevoegen
# ------------------------------
with tabs[3]:
    st.title("💩 Luier toevoegen")
    col1, col2 = st.columns(2)
    with col1:
        tijdstip = st.time_input("Tijdstip", datetime.now().time(), key="luier_tijd")
    with col2:
        type_luier = st.selectbox("Type luier", ["Plas","Poep","Beiden"], key="luier_type")
    opmerking = st.text_input("Opmerking", key="luier_opmerking")

    if st.button("Opslaan luier", key="luier_btn"):
        nieuwe_id = f"R{len(baby_records)+1:03}"
        start_dt = pd.Timestamp(datetime.combine(datetime.today(), tijdstip), tz=LOCAL_TZ)
        sheet_baby.append_row([nieuwe_id,"Luier",start_dt.strftime("%Y-%m-%d %H:%M"),"",1,opmerking,type_luier])
        update_voorraad("Luiers",-1)
        st.success("Luier toegevoegd en voorraad bijgewerkt!")

# ------------------------------
# TAB: Voorraad
# ------------------------------
with tabs[5]:
    st.title("📦 Voorraad beheren")
    
    # Huidige voorraad weergeven
    for i, row in voorraad.iterrows():
        st.write(f"{row['Productnaam']}: {row['Actuele voorraad']} (Min {row['Minimum voorraad']})")

    # --------------------------
    # Voorraad bijvullen
    # --------------------------
    st.subheader("Bijvullen")
    prod_to_add = st.selectbox("Product", voorraad['Productnaam'], key="bijvullen_prod")
    hoeveelheid_to_add = st.number_input("Aantal toevoegen", min_value=1, key="bijvullen_aantal")
    if st.button("Voorraad bijvullen", key="bijvullen_btn"):
        update_voorraad(prod_to_add, hoeveelheid_to_add)
        sheet_bijvulling.append_row([datetime.now().strftime("%Y-%m-%d %H:%M"), prod_to_add, hoeveelheid_to_add])
        st.success("Voorraad bijgewerkt!")

    # --------------------------
    # Voorraad verwijderen
    # --------------------------
    st.subheader("Verwijderen uit voorraad")
    prod_to_remove = st.selectbox("Product", voorraad['Productnaam'], key="verwijder_prod")
    hoeveelheid_to_remove = st.number_input("Aantal verwijderen", min_value=1, max_value=int(voorraad.loc[voorraad['Productnaam']==prod_to_remove,'Actuele voorraad'].values[0]), key="verwijder_aantal")
    if st.button("Voorraad verminderen", key="verwijder_btn"):
        update_voorraad(prod_to_remove, -hoeveelheid_to_remove)
        st.success("Voorraad verminderd!")


# ------------------------------
# TAB: Gezondheid toevoegen
# ------------------------------
with tabs[4]:
    st.title("🩺 Gezondheid toevoegen")
    col1, col2 = st.columns(2)
    with col1:
        gewicht = st.number_input("Gewicht (kg)", min_value=0.0, step=0.1, key="gez_gewicht")
        lengte = st.number_input("Lengte (cm)", min_value=0.0, step=0.1, key="gez_lengte")
    with col2:
        temperatuur = st.number_input("Temperatuur (°C)", min_value=36.5, max_value=45.0, step=0.1, key="gez_temp")
    opmerkingen = st.text_area("Opmerkingen / ziekten", key="gez_opmerkingen")

    if st.button("Opslaan gezondheid", key="gez_btn"):
        nieuwe_id = f"R{len(baby_records)+1:03}"
        sheet_baby.append_row([nieuwe_id,"Gezondheid",pd.Timestamp.now(tz=LOCAL_TZ).strftime("%Y-%m-%d %H:%M"),"",
                               "",gewicht,lengte,temperatuur,opmerkingen])
        st.success("Gezondheid toegevoegd!")

# ------------------------------
# TAB: Bewerk records
# ------------------------------
with tabs[6]:
    st.title("✏️ Bewerk bestaand record")
    record_type = st.selectbox("Kies type record", ["Slaap","Voeding","Luier","Gezondheid"])
    df_type = baby_records[baby_records['Type']==record_type].sort_values("Starttijd", ascending=False)

    if df_type.empty:
        st.info("Geen records beschikbaar.")
    else:
        options = df_type['Starttijd'].dt.strftime("%Y-%m-%d %H:%M").tolist()
        selected = st.selectbox(f"Selecteer {record_type} record", options)

        if selected:
            rij_index = df_type[df_type['Starttijd'].dt.strftime("%Y-%m-%d %H:%M")==selected].index[0]+2
            record = df_type.loc[rij_index-2]

            if record_type == "Slaap":
                starttijd = st.time_input("Starttijd", record['Starttijd'].time())
                duur = st.number_input("Duur (minuten)", value=int(record['Hoeveelheid']), min_value=1)
                opmerking = st.text_input("Opmerking", record.get('Opmerking',''))

                if st.button("Opslaan wijzigingen slaap"):
                    start_dt = datetime.combine(datetime.today(), starttijd)
                    sheet_baby.update_cell(rij_index,3,start_dt.strftime("%Y-%m-%d %H:%M"))
                    sheet_baby.update_cell(rij_index,4,(start_dt+pd.Timedelta(minutes=duur)).strftime("%Y-%m-%d %H:%M"))
                    sheet_baby.update_cell(rij_index,5,duur)
                    sheet_baby.update_cell(rij_index,6,opmerking)
                    st.success("Slaaprecord aangepast!")

            elif record_type == "Voeding":
                starttijd = st.time_input("Tijdstip", record['Starttijd'].time())
                hoeveelheid = st.number_input("Hoeveelheid (ml)", value=int(record.get('Hoeveelheid',0)), min_value=0)
                borst = st.text_input("Borst", record.get('Borst',''))
                kolven = st.text_input("Kolven", record.get('Kolven',''))
                verhouding = st.text_input("Verhouding", record.get('Verhouding',''))
                opmerking = st.text_input("Opmerking", record.get('Opmerking',''))

                if st.button("Opslaan wijzigingen voeding"):
                    start_dt = datetime.combine(datetime.today(), starttijd)
                    sheet_baby.update_cell(rij_index,3,start_dt.strftime("%Y-%m-%d %H:%M"))
                    sheet_baby.update_cell(rij_index,5,hoeveelheid)
                    sheet_baby.update_cell(rij_index,7,borst)
                    sheet_baby.update_cell(rij_index,8,kolven)
                    sheet_baby.update_cell(rij_index,9,verhouding)
                    sheet_baby.update_cell(rij_index,6,opmerking)
                    st.success("Voedingsrecord aangepast!")

            elif record_type == "Luier":
                starttijd = st.time_input("Tijdstip", record['Starttijd'].time())
                type_luier = st.selectbox("Type luier", ["Plas","Poep","Beiden"], index=["Plas","Poep","Beiden"].index(record.get('Type Luier','Plas')))
                opmerking = st.text_input("Opmerking", record.get('Opmerking',''))

                if st.button("Opslaan wijzigingen luier"):
                    start_dt = datetime.combine(datetime.today(), starttijd)
                    sheet_baby.update_cell(rij_index,3,start_dt.strftime("%Y-%m-%d %H:%M"))
                    sheet_baby.update_cell(rij_index,6,opmerking)
                    sheet_baby.update_cell(rij_index,7,type_luier)
                    st.success("Luierrecord aangepast!")

            elif record_type == "Gezondheid":
                gewicht = st.number_input("Gewicht (kg)", value=float(record.get('Gewicht',0.0)))
                lengte = st.number_input("Lengte (cm)", value=float(record.get('Lengte',0.0)))
                temperatuur = st.number_input("Temperatuur (°C)", value=float(record.get('Temperatuur',0.0)))
                opmerkingen = st.text_area("Opmerkingen / ziekten", record.get('Opmerkingen / ziekten',''))

                if st.button("Opslaan wijzigingen gezondheid"):
                    sheet_baby.update_cell(rij_index,6,gewicht)
                    sheet_baby.update_cell(rij_index,7,lengte)
                    sheet_baby.update_cell(rij_index,8,temperatuur)
                    sheet_baby.update_cell(rij_index,9,opmerkingen)
                    st.success("Gezondheidsrecord aangepast!")
