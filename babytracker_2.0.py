import os
import json
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, date, time
from zoneinfo import ZoneInfo
from streamlit_option_menu import option_menu
from supabase import create_client, Client
from streamlit_cookies_controller import CookieController
import altair as alt

# ------------------------------
# Config
# ------------------------------
st.set_page_config(page_title="Bubbel.", page_icon="🫧", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 3.5rem !important; }
</style>
""", unsafe_allow_html=True)

# ------------------------------
# Supabase setup
# ------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

@st.cache_resource
def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = get_supabase()

# ------------------------------
# Authenticatie
# ------------------------------
COOKIE_NAME = "bubbel_session"
COOKIE_REFRESH = "bubbel_refresh"
COOKIE_EXPIRY_DAYS = 90

def get_cookie_manager():
    return CookieController(key="bubbel_cookies")

def get_session_from_cookie(cm):
    try:
        refresh_token = cm.get(COOKIE_REFRESH)
        if refresh_token and len(refresh_token) > 10:
            res = supabase.auth.refresh_session(refresh_token)
            if res and res.user:
                cm.set(COOKIE_REFRESH, res.session.refresh_token,
                       max_age=COOKIE_EXPIRY_DAYS * 86400)
                return {"access_token": res.session.access_token, "user": res.user}
    except Exception:
        pass
    try:
        token = cm.get(COOKIE_NAME)
        if token and len(token) > 10:
            user = supabase.auth.get_user(token)
            if user and user.user:
                return {"access_token": token, "user": user.user}
    except Exception:
        pass
    return None

def login(email, wachtwoord, cm, onthoud=True):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": wachtwoord})
        if res.user:
            st.session_state["session"] = {"access_token": res.session.access_token, "user": res.user}
            if onthoud:
                try:
                    cm.set(COOKIE_NAME, res.session.access_token,
                           max_age=COOKIE_EXPIRY_DAYS * 86400)
                    cm.set(COOKIE_REFRESH, res.session.refresh_token,
                           max_age=COOKIE_EXPIRY_DAYS * 86400)
                except Exception:
                    pass
            return True, None
    except Exception as e:
        return False, str(e)
    return False, "Onbekende fout"

def registreer(email, wachtwoord, cm):
    try:
        res = supabase.auth.sign_up({"email": email, "password": wachtwoord})
        if res.user:
            return login(email, wachtwoord, cm)
    except Exception as e:
        return False, str(e)
    return False, "Onbekende fout"

def uitloggen(cm):
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    try:
        cm.remove(COOKIE_NAME)
        cm.remove(COOKIE_REFRESH)
    except Exception:
        pass
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

def wachtwoord_reset_email(email):
    try:
        app_url = os.environ.get("APP_URL", "")
        opts = {"redirect_to": app_url} if app_url else {}
        supabase.auth.reset_password_email(email, opts)
        return True, None
    except Exception as e:
        return False, str(e)

def toon_login_scherm(cm):
    st.markdown("""
    <div style="max-width:400px;margin:80px auto 0;">
    """, unsafe_allow_html=True)
    col = st.columns([1, 3, 1])[1]
    with col:
        st.markdown("""
        <div style="text-align:center;margin-bottom:32px;">
            <span style="font-size:40px;font-weight:800;letter-spacing:-1px;">Bubbel</span><span style="font-size:40px;font-weight:800;color:#7a9e72;">.</span>
            <div style="font-size:14px;color:#aaa;margin-top:4px;">De babytracker voor jouw gezin</div>
        </div>
        """, unsafe_allow_html=True)

        tab_in, tab_reg = st.tabs(["Inloggen", "Registreren"])

        with tab_in:
            email = st.text_input("E-mailadres", key="login_email")
            ww = st.text_input("Wachtwoord", type="password", key="login_ww")
            onthoud = st.checkbox("Ingelogd blijven", value=True, key="login_onthoud")
            if st.button("Inloggen", use_container_width=True, key="login_btn"):
                if email and ww:
                    ok, err = login(email, ww, cm, onthoud=onthoud)
                    if ok:
                        st.rerun()
                    else:
                        st.error(f"Inloggen mislukt: {err}")
                else:
                    st.warning("Vul e-mail en wachtwoord in")
            app_url = os.environ.get("APP_URL", "")
            reset_url = f"{app_url}?pagina=reset" if app_url else "?pagina=reset"
            st.markdown(
                f'''<div style="text-align:right;margin-top:6px;">
                    <a href="{reset_url}" target="_blank"
                       style="font-size:13px;color:#7a9e72;text-decoration:none;">
                        Wachtwoord vergeten?
                    </a>
                </div>''',
                unsafe_allow_html=True
            )

        with tab_reg:
            r_email = st.text_input("E-mailadres", key="reg_email")
            r_ww = st.text_input("Wachtwoord (min. 6 tekens)", type="password", key="reg_ww")
            r_ww2 = st.text_input("Wachtwoord herhalen", type="password", key="reg_ww2")
            if st.button("Account aanmaken", use_container_width=True, key="reg_btn"):
                if not r_email or not r_ww:
                    st.warning("Vul alle velden in")
                elif r_ww != r_ww2:
                    st.error("Wachtwoorden komen niet overeen")
                elif len(r_ww) < 6:
                    st.error("Wachtwoord moet minimaal 6 tekens zijn")
                else:
                    ok, err = registreer(r_email, r_ww, cm)
                    if ok:
                        st.success("Account aangemaakt! Je bent ingelogd.")
                        st.rerun()
                    else:
                        st.error(f"Registratie mislukt: {err}")

    st.stop()

# --- PWA token opvangen (inkomend vanuit de PWA wrapper) ---
qp = st.query_params
pwa_token = qp.get("pwa_token")
if pwa_token and "session" not in st.session_state:
    try:
        user_result = supabase.auth.get_user(pwa_token)
        if user_result and user_result.user:
            st.session_state["session"] = {
                "access_token": pwa_token,
                "user": user_result.user,
            }
            # Token uit URL verwijderen (netter en veiliger)
            st.query_params.clear()
            st.rerun()
    except Exception:
        pass

# --- Wachtwoord reset via e-maillink (token_hash flow) ---
token_hash    = qp.get("token_hash") or st.session_state.get("recovery_token_hash")
recovery_type = qp.get("type", "")

if token_hash and recovery_type == "recovery":
    st.session_state["recovery_token_hash"] = token_hash
    if "token_hash" in qp:
        st.query_params.clear()

if st.query_params.get("pagina") == "reset":
    col = st.columns([1, 3, 1])[1]
    with col:
        st.markdown("""
        <div style="text-align:center;margin-bottom:32px;margin-top:80px;">
            <span style="font-size:40px;font-weight:800;letter-spacing:-1px;">Bubbel</span><span style="font-size:40px;font-weight:800;color:#7a9e72;">.</span>
            <div style="font-size:14px;color:#aaa;margin-top:4px;">Wachtwoord herstellen</div>
        </div>
        """, unsafe_allow_html=True)
        reset_email = st.text_input("E-mailadres", key="reset_email_page")
        if st.button("Stuur resetlink", use_container_width=True, key="reset_send_btn"):
            if reset_email:
                ok, err = wachtwoord_reset_email(reset_email)
                if ok:
                    st.success("E-mail verstuurd! Controleer je inbox en klik op de link.")
                else:
                    st.error(f"Mislukt: {err}")
            else:
                st.warning("Vul je e-mailadres in")
        st.markdown(
            '<div style="text-align:center;margin-top:16px;">' +
            '<a href="/" style="font-size:13px;color:#aaa;text-decoration:none;">← Terug naar inloggen</a>' +
            '</div>',
            unsafe_allow_html=True
        )
    st.stop()

if st.session_state.get("recovery_token_hash"):
    col = st.columns([1, 3, 1])[1]
    with col:
        st.markdown("""
        <div style="text-align:center;margin-bottom:32px;margin-top:80px;">
            <span style="font-size:40px;font-weight:800;letter-spacing:-1px;">Bubbel</span><span style="font-size:40px;font-weight:800;color:#7a9e72;">.</span>
            <div style="font-size:14px;color:#aaa;margin-top:4px;">Nieuw wachtwoord instellen</div>
        </div>
        """, unsafe_allow_html=True)
        nieuw_ww  = st.text_input("Nieuw wachtwoord", type="password", key="reset_nieuw_ww")
        nieuw_ww2 = st.text_input("Wachtwoord herhalen", type="password", key="reset_nieuw_ww2")
        if st.button("Wachtwoord opslaan", use_container_width=True, key="reset_opslaan_btn"):
            if not nieuw_ww:
                st.warning("Vul een nieuw wachtwoord in")
            elif nieuw_ww != nieuw_ww2:
                st.error("Wachtwoorden komen niet overeen")
            elif len(nieuw_ww) < 6:
                st.error("Wachtwoord moet minimaal 6 tekens zijn")
            else:
                try:
                    res = supabase.auth.verify_otp({
                        "token_hash": st.session_state["recovery_token_hash"],
                        "type": "recovery"
                    })
                    supabase.auth.update_user({"password": nieuw_ww})
                    st.success("Wachtwoord gewijzigd! Je kunt nu inloggen.")
                    st.session_state.pop("recovery_token_hash", None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Mislukt: {e}")
    st.stop()

# --- Sessie controleren ---
cm = get_cookie_manager()

if "session" not in st.session_state:
    sessie = get_session_from_cookie(cm)
    if sessie:
        st.session_state["session"] = sessie
        st.rerun()
    else:
        toon_login_scherm(cm)

user_id = st.session_state["session"]["user"].id

# ------------------------------
# Data laden vanuit Supabase
# ------------------------------
@st.cache_data(ttl=30)
def load_data(uid: str):
    errors = []
    def query(table):
        try:
            res = supabase.table(table).select("*").eq("user_id", uid).execute()
            return pd.DataFrame(res.data) if res.data else pd.DataFrame()
        except Exception as e:
            errors.append(f"{table}: {e}")
            return pd.DataFrame()

    baby_records = query("baby_records")
    voorraad     = query("voorraad")
    bijvullingen = query("voorraad_bijvulling")
    activiteiten = query("activiteiten")
    gebruik_logs = query("voorraad_gebruik_log")
    opvangdagen  = query("opvangdagen")

    def parse_numeric(df, field):
        if field in df.columns:
            df[field] = pd.to_numeric(df[field].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

    if not baby_records.empty:
        for field in ['hoeveelheid', 'gewicht', 'lengte', 'temperatuur']:
            parse_numeric(baby_records, field)
        for col in ['starttijd', 'eindtijd']:
            if col in baby_records.columns:
                baby_records[col] = pd.to_datetime(baby_records[col], errors='coerce')
        baby_records = baby_records.rename(columns={
            'starttijd': 'Starttijd', 'eindtijd': 'Eindtijd', 'type': 'Type',
            'hoeveelheid': 'Hoeveelheid', 'opmerking': 'Opmerking',
            'borst': 'Borst', 'kolven': 'Kolven', 'fles': 'Fles',
            'voeding_type': 'Voeding_type', 'hapje_type': 'Hapje_type',
            'type_luier': 'Type Luier', 'gewicht': 'Gewicht',
            'lengte': 'Lengte', 'temperatuur': 'Temperatuur',
            'opmerkingen': 'Opmerkingen / ziekten',
        })

    if not bijvullingen.empty:
        bijvullingen = bijvullingen.rename(columns={
            'datum': 'Datum', 'productnaam': 'Productnaam', 'hoeveelheid': 'Hoeveelheid'
        })
        bijvullingen['Datum'] = pd.to_datetime(bijvullingen['Datum'], errors='coerce')

    if not activiteiten.empty:
        parse_numeric(activiteiten, 'duur')
        for col in ['starttijd', 'eindtijd']:
            if col in activiteiten.columns:
                activiteiten[col] = pd.to_datetime(activiteiten[col], errors='coerce')
        activiteiten = activiteiten.rename(columns={
            'starttijd': 'Starttijd', 'eindtijd': 'Eindtijd', 'duur': 'Duur',
            'activiteit_type': 'Activiteit_type', 'reactie': 'Reactie', 'opmerking': 'Opmerking'
        })

    if not voorraad.empty:
        voorraad = voorraad.rename(columns={
            'productnaam': 'Productnaam', 'variant': 'Variant', 'eenheid': 'Eenheid',
            'actuele_voorraad': 'Actuele voorraad', 'minimum_voorraad': 'Minimum voorraad'
        })

    if not gebruik_logs.empty:
        gebruik_logs = gebruik_logs.rename(columns={
            'datum': 'Datum', 'productnaam': 'Productnaam', 'hoeveelheid': 'Hoeveelheid'
        })
        gebruik_logs['Datum'] = pd.to_datetime(gebruik_logs['Datum'], errors='coerce')

    # Opvangdagen: zet datum kolom om naar python date objecten
    if not opvangdagen.empty:
        opvangdagen['datum'] = pd.to_datetime(opvangdagen['datum'], errors='coerce').dt.date

    return baby_records, voorraad, bijvullingen, activiteiten, gebruik_logs, opvangdagen, errors

baby_records, voorraad, bijvullingen, activiteiten, gebruik_logs, opvangdagen, _load_errors = load_data(user_id)
if _load_errors:
    for err in _load_errors:
        st.error(f"⚠️ Datafout: {err}")

# ------------------------------
# Opvangdag helpers
# ------------------------------
def get_vaste_opvangdagen() -> set:
    """Geeft een set van weekdag-indices (0=ma … 6=zo) die als vaste opvangdag zijn ingesteld."""
    try:
        return set(json.loads(inst.get('vaste_opvangdagen', '[]')))
    except Exception:
        return set()

def get_uitzonderingen() -> dict:
    """
    Geeft een dict van {date: type} voor handmatige uitzonderingen:
      type='skip'  → vaste opvangdag overgeslagen (bijv. vakantie)
      type='extra' → extra opvangdag buiten het vaste patroon
    """
    if opvangdagen.empty:
        return {}
    result = {}
    for _, row in opvangdagen.iterrows():
        d = row.get('datum')
        t = row.get('type', 'extra')
        if d:
            result[d] = t
    return result

def is_opvangdag(d: date) -> bool:
    """Bepaalt of een dag een opvangdag is, op basis van vaste weekdagen + uitzonderingen."""
    vaste = get_vaste_opvangdagen()
    uitz  = get_uitzonderingen()
    if d in uitz:
        return uitz[d] == 'extra'   # 'skip' = geen opvangdag; 'extra' = wel
    # Controleer startdatum: vaste dagen gelden pas vanaf de ingestelde datum
    startdatum_str = inst.get('opvang_startdatum', '')
    if startdatum_str:
        try:
            startdatum = date.fromisoformat(startdatum_str)
            if d < startdatum:
                return False
        except Exception:
            pass
    return d.weekday() in vaste

def get_opvangdagen_set(vanaf: date = None, tot: date = None) -> set:
    """Geeft een set van date-objecten die als opvangdag gelden in een periode."""
    if vanaf is None:
        vanaf = date.today() - timedelta(days=60)
    if tot is None:
        tot = date.today() + timedelta(days=1)
    result = set()
    d = vanaf
    while d <= tot:
        if is_opvangdag(d):
            result.add(d)
        d += timedelta(days=1)
    return result

def markeer_opvangdag(d: date):
    """Markeer een dag als opvangdag. Als het een vaste dag is: verwijder een eventuele skip-uitzondering.
    Anders: voeg een extra-uitzondering toe."""
    vaste = get_vaste_opvangdagen()
    uitz  = get_uitzonderingen()
    try:
        if d.weekday() in vaste:
            # Was een vaste dag met skip → verwijder de skip
            if d in uitz and uitz[d] == 'skip':
                supabase.table("opvangdagen").delete().eq("user_id", user_id).eq("datum", d.isoformat()).execute()
        else:
            # Geen vaste dag → voeg extra toe
            supabase.table("opvangdagen").upsert(
                {"user_id": user_id, "datum": d.isoformat(), "type": "extra"},
                on_conflict="user_id,datum"
            ).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Kon dag niet markeren: {e}")

def verwijder_opvangdag(d: date):
    """Verwijder een opvangdag. Als het een vaste dag is: voeg een skip-uitzondering toe.
    Anders: verwijder de extra-uitzondering."""
    vaste = get_vaste_opvangdagen()
    try:
        if d.weekday() in vaste:
            # Vaste dag → skip toevoegen
            supabase.table("opvangdagen").upsert(
                {"user_id": user_id, "datum": d.isoformat(), "type": "skip"},
                on_conflict="user_id,datum"
            ).execute()
        else:
            # Extra dag → verwijderen
            supabase.table("opvangdagen").delete().eq("user_id", user_id).eq("datum", d.isoformat()).execute()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Kon markering niet verwijderen: {e}")

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
    'gezondheid_default_gewicht': '0',
    'gezondheid_default_lengte': '0',
    'gezondheid_default_temp': '0',
    'vaste_opvangdagen': '[]',
    'opvangdagen_aan': 'nee',
    'opvang_startdatum': '',
}

@st.cache_data(ttl=60)
def load_instellingen(uid: str):
    try:
        res = supabase.table("instellingen").select("sleutel, waarde").eq("user_id", uid).execute()
        inst = DEFAULTS.copy()
        if res.data:
            for row in res.data:
                inst[row['sleutel']] = row['waarde']
        return inst
    except Exception:
        return DEFAULTS.copy()

def save_instelling(sleutel, waarde):
    try:
        supabase.table("instellingen").upsert(
            {"user_id": user_id, "sleutel": sleutel, "waarde": str(waarde)},
            on_conflict="user_id,sleutel"
        ).execute()
    except Exception as e:
        st.error(f"Kon instelling niet opslaan: {e}")

inst = load_instellingen(user_id)

# ------------------------------
# Datetime helpers
# ------------------------------
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Amsterdam"))

def get_device_datetime(time_input: time, date_input: date = None):
    if date_input is None:
        date_input = datetime.now(TZ).date()
    return datetime.combine(date_input, time_input)

# ------------------------------
# Voorraad helpers
# ------------------------------

def update_voorraad(productnaam, hoeveelheid):
    if voorraad.empty:
        st.warning("Voorraad niet beschikbaar")
        return
    mask = voorraad['Productnaam'] == productnaam
    if not mask.any():
        st.error("Product niet gevonden")
        return
    row = voorraad[mask].iloc[0]
    nieuw = max(0, round(float(row.get('Actuele voorraad', 0) or 0) + hoeveelheid, 1))
    try:
        supabase.table("voorraad").update({"actuele_voorraad": nieuw}).eq("user_id", user_id).eq("productnaam", productnaam).execute()
    except Exception as e:
        st.error(f"Kon voorraad niet updaten: {e}")

def log_gebruik(productnaam, hoeveelheid):
    try:
        supabase.table("voorraad_gebruik_log").insert({
            "user_id": user_id,
            "datum": datetime.now(TZ).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M'),
            "productnaam": productnaam,
            "hoeveelheid": abs(hoeveelheid),
        }).execute()
    except Exception as e:
        st.error(f"Kon gebruik niet loggen: {e}")

def is_handmatig(productnaam):
    handmatig_raw = inst.get('handmatige_producten', '[]')
    try:
        import json as _j
        handmatig_lijst = _j.loads(handmatig_raw)
    except Exception:
        handmatig_lijst = []
    return productnaam in handmatig_lijst

# ------------------------------
# Record helpers
# ------------------------------
def add_record(record_type, values, rerun=False):
    kolommen = ['starttijd','eindtijd','hoeveelheid','opmerking','type_luier',
                'borst','kolven','fles','voeding_type','hapje_type',
                'gewicht','lengte','temperatuur','opmerkingen']
    try:
        data = {"user_id": user_id, "type": record_type}
        for i, k in enumerate(kolommen):
            if i < len(values) and values[i] not in ('', None):
                data[k] = values[i]
        supabase.table("baby_records").insert(data).execute()
        if rerun:
            st.cache_data.clear()
            st.rerun()
        return True
    except Exception as e:
        st.error(f"Kon niet toevoegen: {e}")
        return False

def add_activiteit(start_dt, end_dt, duur, activiteit_type, reactie, opm):
    try:
        supabase.table("activiteiten").insert({
            "user_id": user_id,
            "starttijd": start_dt,
            "eindtijd": end_dt,
            "duur": duur,
            "activiteit_type": activiteit_type,
            "reactie": reactie,
            "opmerking": opm,
        }).execute()
        return True
    except Exception as e:
        st.error(f"Kon activiteit niet opslaan: {e}")
        return False

def edit_record(record_id, updates, rerun=False):
    try:
        supabase.table("baby_records").update(updates).eq("id", record_id).eq("user_id", user_id).execute()
        st.success("Record aangepast ✅")
        if rerun:
            st.cache_data.clear()
            st.rerun()
        return True
    except Exception as e:
        st.error(f"Kon niet updaten: {e}")
        return False

def parse_eigen_activiteiten(raw: str) -> list:
    """
    Parseert eigen activiteiten. Ondersteunt zowel het oude formaat (lijst van strings)
    als het nieuwe formaat (lijst van dicts met 'naam' en 'icon').
    Geeft altijd een lijst van dicts terug: [{"naam": "...", "icon": "..."}]
    """
    try:
        data = json.loads(raw) if raw else []
    except Exception:
        return []
    result = []
    for item in data:
        if isinstance(item, str):
            result.append({"naam": item, "icon": "🎈"})
        elif isinstance(item, dict):
            result.append({"naam": item.get("naam", ""), "icon": item.get("icon", "🎈")})
    return result

# ------------------------------
# Sidebar menu
# ------------------------------
TAB_NAMES = ["Dashboard", "Slaap", "Voeding", "Luiers", "Gezondheid", "Activiteiten", "Voorraad", "Analyse", "Data", "Bewerk records", "Instellingen", "Info"]
TAB_ICONS = ["house", "moon", "cup-straw", "droplet", "heart", "balloon", "cart", "graph-up", "table", "pencil", "gear", "info-circle"]

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
    st.divider()
    user_email = st.session_state["session"]["user"].email
    st.caption(f"Ingelogd als {user_email}")
    col_ref, col_uit = st.columns(2)
    with col_ref:
        if st.button("Vernieuwen", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with col_uit:
        if st.button("Uitloggen", use_container_width=True):
            uitloggen(cm)

if st.session_state.get("selected_tab") != selected_from_menu:
    st.session_state.selected_tab = selected_from_menu

selected_tab = st.session_state.selected_tab

# ------------------------------
# TAB: Dashboard
# ------------------------------
if selected_tab == "Dashboard":
    baby_naam = inst.get('baby_naam', 'Bubbel')
    MAANDEN_NL = ['januari','februari','maart','april','mei','juni','juli','augustus','september','oktober','november','december']

    col_titel, col_datum = st.columns([3, 2])
    with col_datum:
        dag_keuze = st.segmented_control("Dag", ["Vandaag", "Gisteren", "Eerder"], default="Vandaag", key="dash_dag_pills", label_visibility="collapsed")

    if dag_keuze == "Vandaag":
        gekozen_datum = datetime.now(TZ).date()
    elif dag_keuze == "Gisteren":
        gekozen_datum = datetime.now(TZ).date() - timedelta(days=1)
    else:
        gekozen_datum = st.date_input("Kies datum", value=st.session_state.get("dash_datum_waarde", datetime.now(TZ).date()), key="dash_datum_input", label_visibility="collapsed")
        st.session_state["dash_datum_waarde"] = gekozen_datum
    vandaag = gekozen_datum
    is_vandaag = vandaag == datetime.now(TZ).date()
    datum_str = f"{vandaag.day} {MAANDEN_NL[vandaag.month - 1]}"

    geboortedatum_str = inst.get('geboortedatum', '')
    leeftijd_str = ''
    if geboortedatum_str:
        try:
            gbd = date.fromisoformat(geboortedatum_str)
            dagen_oud = (vandaag - gbd).days
            weken = dagen_oud // 7
            maanden = (vandaag.year - gbd.year) * 12 + (vandaag.month - gbd.month)
            if vandaag.day < gbd.day:
                maanden -= 1
            if maanden < 3:
                leeftijd_str = f"{weken} weken oud"
            elif maanden < 24:
                leeftijd_str = f"{maanden} maanden oud"
            else:
                jaar = maanden // 12
                rest_m = maanden % 12
                leeftijd_str = f"{jaar} jaar en {rest_m} maanden oud" if rest_m > 0 else f"{jaar} jaar oud"
        except Exception:
            pass

    with col_titel:
        dag_label = "Dagoverzicht" if is_vandaag else "Overzicht"
        leeftijd_html = f" · {leeftijd_str}" if leeftijd_str else ""
        st.markdown(f"""
<div style="margin-bottom:20px;">
  <div style="font-size:28px;font-weight:800;letter-spacing:-1px;line-height:1.1;">Bubbel<span style="color:#7a9e72;">.</span></div>
  <div style="font-size:13px;color:#aaa;margin-top:3px;">{dag_label} van {baby_naam} · {datum_str}{leeftijd_html}</div>
</div>
""", unsafe_allow_html=True)

    # --- Opvangdag status bepalen (banner + knop komen later in de pagina) ---
    dag_is_opvang = is_opvangdag(vandaag)

    # Slaap: ook slaapjes die van gisteren doorlopen naar vandaag meenemen
    vorige_dag = vandaag - timedelta(days=1)
    if not baby_records.empty:
        slaap_start_vandaag = baby_records[
            (baby_records['Type'] == 'Slaap') &
            (baby_records['Starttijd'].dt.date == vandaag)
        ].copy()
        slaap_doorloop = baby_records[
            (baby_records['Type'] == 'Slaap') &
            (baby_records['Starttijd'].dt.date == vorige_dag)
        ].copy()
        if not slaap_doorloop.empty:
            slaap_doorloop['Eindtijd_dt'] = pd.to_datetime(slaap_doorloop['Eindtijd'], errors='coerce')
            slaap_doorloop = slaap_doorloop[slaap_doorloop['Eindtijd_dt'].dt.date >= vandaag]
        slaap_df = pd.concat([slaap_start_vandaag, slaap_doorloop]).drop_duplicates(subset=['id']) if not slaap_doorloop.empty else slaap_start_vandaag
    else:
        slaap_df = pd.DataFrame()

    voeding_df = baby_records[(baby_records['Type'] == 'Voeding') & (baby_records['Starttijd'].dt.date == vandaag)] if not baby_records.empty else pd.DataFrame()
    luier_df = baby_records[(baby_records['Type'] == 'Luier') & (baby_records['Starttijd'].dt.date == vandaag)] if not baby_records.empty else pd.DataFrame()
    act_vandaag = activiteiten[activiteiten['Starttijd'].dt.date == vandaag] if not activiteiten.empty else pd.DataFrame()
    gez_df = baby_records[baby_records['Type'] == 'Gezondheid'] if not baby_records.empty else pd.DataFrame()

    aantal_slaap = len(slaap_df)
    laatste_slaap = slaap_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M') if not slaap_df.empty else None
    totaal_slaap_min = 0
    if not slaap_df.empty and 'Eindtijd' in slaap_df.columns:
        slaap_df2 = slaap_df.copy()
        slaap_df2['Eindtijd_dt'] = pd.to_datetime(slaap_df2['Eindtijd'], errors='coerce')
        dag_start = pd.Timestamp(vandaag).tz_localize('UTC')
        dag_eind  = (pd.Timestamp(vandaag) + pd.Timedelta(days=1)).tz_localize('UTC')
        if slaap_df2['Starttijd'].dt.tz is None:
            slaap_df2['Starttijd'] = slaap_df2['Starttijd'].dt.tz_localize('UTC')
        if slaap_df2['Eindtijd_dt'].dt.tz is None:
            slaap_df2['Eindtijd_dt'] = slaap_df2['Eindtijd_dt'].dt.tz_localize('UTC')
        slaap_df2['start_geknipt'] = slaap_df2['Starttijd'].clip(lower=dag_start)
        slaap_df2['eind_geknipt']  = slaap_df2['Eindtijd_dt'].clip(upper=dag_eind)
        slaap_df2['duur'] = (slaap_df2['eind_geknipt'] - slaap_df2['start_geknipt']).dt.total_seconds() / 60
        totaal_slaap_min = int(slaap_df2['duur'].clip(lower=0).fillna(0).sum())
    slaap_tag = f"{totaal_slaap_min // 60}u {totaal_slaap_min % 60}m totaal" if totaal_slaap_min > 0 else "–"

    voeding_gegeven_df = voeding_df[voeding_df['Voeding_type'] != 'Kolven'] if not voeding_df.empty else pd.DataFrame()
    borst_df = voeding_df[voeding_df['Voeding_type'] == 'Borst'] if not voeding_df.empty else pd.DataFrame()
    fles_df  = voeding_df[voeding_df['Voeding_type'].isin(['Fles','Hapje'])] if not voeding_df.empty else pd.DataFrame()

    aantal_voeding = len(voeding_gegeven_df)
    laatste_voeding = voeding_gegeven_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M') if not voeding_gegeven_df.empty else None
    totaal_ml = fles_df['Hoeveelheid'].sum() if not fles_df.empty else 0

    aantal_borst = len(borst_df)
    heeft_borst = aantal_borst > 0
    heeft_fles  = len(fles_df) > 0

    nat_count = len(luier_df[luier_df['Type Luier'] == 'Nat']) if not luier_df.empty else 0
    vuil_count = len(luier_df[luier_df['Type Luier'] == 'Vuil']) if not luier_df.empty else 0
    laatste_luier = luier_df.sort_values('Starttijd', ascending=False).iloc[0]['Starttijd'].strftime('%H:%M') if not luier_df.empty else None

    aantal_act = len(act_vandaag)
    if not act_vandaag.empty:
        laatste_act_row = act_vandaag.sort_values('Starttijd', ascending=False).iloc[0]
        laatste_act_naam = laatste_act_row.get('Activiteit_type', '') if 'Activiteit_type' in laatste_act_row.index else ''
        laatste_act_tijd = laatste_act_row['Starttijd'].strftime('%H:%M')
    else:
        laatste_act_naam = '–'
        laatste_act_tijd = None

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

    timeline_items = []
    if not slaap_df.empty:
        dag_start_ts = pd.Timestamp(vandaag)
        if not slaap_df.empty and slaap_df['Starttijd'].dt.tz is not None:
            dag_start_ts = dag_start_ts.tz_localize('UTC')
        for _, r in slaap_df.iterrows():
            is_doorloop = r['Starttijd'].date() < vandaag
            start_label = "Slaap doorgelopen" if is_doorloop else "Slaap gestart"
            toon_tijd = dag_start_ts if is_doorloop else r['Starttijd']
            timeline_items.append(("💤", toon_tijd, start_label, "#e8f4fd"))
            if pd.notna(r.get('Eindtijd')) and r.get('Eindtijd') != '':
                eind = pd.to_datetime(r.get('Eindtijd'), errors='coerce')
                if pd.notna(eind) and eind.date() == vandaag:
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
    ACTIVITEIT_ICONS = {naam: icon for icon, naam in [
        ("🐛", "Tummy time"), ("🛁", "Bad"), ("🚿", "Douchen"), ("🚶", "Wandelen"),
        ("🏊", "Zwemmen"), ("👨‍👩‍👧", "Familie/vrienden"), ("🏥", "CJG/Dokter"),
        ("🧸", "Speelmat"), ("🧣", "Draagdoek"),
    ]}

    if not act_vandaag.empty:
        for _, r in act_vandaag.iterrows():
            anaam = r.get('Activiteit_type', 'Activiteit') if 'Activiteit_type' in r.index else 'Activiteit'
            aicon = ACTIVITEIT_ICONS.get(anaam, "🎈")
            timeline_items.append((aicon, r['Starttijd'], anaam, "#fff7ed"))

    timeline_items.sort(key=lambda x: x[1], reverse=True)

    timeline_html = ""
    for icon, tijd, label, bg in timeline_items:
        tijd_str = tijd.strftime('%H:%M') if pd.notna(tijd) else ''
        is_nacht = pd.notna(tijd) and (tijd.hour < 6 or tijd.hour >= 22)
        item_bg = "#f0f4ff" if is_nacht else bg
        nacht_label = '<span style="font-size:10px;color:#9b84c4;margin-left:4px;">nacht</span>' if is_nacht else ''
        timeline_html += f"""
<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;position:relative;">
  <div style="width:28px;height:28px;border-radius:50%;background:{item_bg};display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0;">{icon}</div>
  <div style="flex:1;font-size:13px;font-weight:500;">{label}{nacht_label}</div>
  <div style="font-size:11px;color:#bbb;white-space:nowrap;">{tijd_str}</div>
</div>"""

    if voorraad_items_html:
        st.markdown(f"""
<div style="background:#fef3f2;border:1px solid #fecdca;border-radius:14px;padding:12px 16px;margin-bottom:16px;display:flex;gap:10px;align-items:flex-start;">
  <span style="font-size:18px;">⚠️</span>
  <div>
    <div style="font-weight:700;font-size:13px;color:#b42318;margin-bottom:2px;">Lage voorraad</div>
    {voorraad_items_html}
  </div>
</div>""", unsafe_allow_html=True)

    # Dim kaarten licht als het een opvangdag is (visuele hint, niet geblokkeerd)
    kaart_opacity = "0.5" if dag_is_opvang else "1"

    k1, k2 = st.columns(2)
    k3, k4 = st.columns(2)

    def dash_kaart(col, icon, titel, getal, subtekst, tag_tekst, tag_bg, tag_kleur, laatste=None):
        laatste_html = f'<span style="font-size:11px;color:#aaa;">{laatste}</span>' if laatste else ''
        with col.container(border=True):
            st.markdown(f"""
<div style="opacity:{kaart_opacity};">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
  <div style="display:flex;align-items:center;gap:6px;">
    <span style="font-size:16px;">{icon}</span>
    <span style="font-weight:700;font-size:13px;">{titel}</span>
  </div>
  {laatste_html}
</div>
<div style="font-size:34px;font-weight:800;letter-spacing:-1px;line-height:1;margin:4px 0 2px;">{getal}</div>
<div style="font-size:11px;color:#aaa;margin-bottom:10px;">{subtekst}</div>
<div style="padding-bottom:10px;">
  <span style="background:{tag_bg};color:{tag_kleur};font-size:11px;font-weight:700;padding:3px 8px;border-radius:99px;">{tag_tekst}</span>
</div>
</div>
""", unsafe_allow_html=True)

    dash_kaart(k1, "💤", "Slaap",
               aantal_slaap, "slaapjes vandaag", slaap_tag,
               "#e8f4fd", "#1a6fa8",
               laatste=f"laatste {laatste_slaap}" if laatste_slaap else None)

    if heeft_borst and not heeft_fles:
        voeding_tag = f"{aantal_borst}x borst"
        voeding_subtag_bg, voeding_subtag_kleur = "#fdf4ff", "#7c3aed"
    elif heeft_fles and not heeft_borst:
        voeding_tag = f"{totaal_ml:.0f} ml totaal" if totaal_ml > 0 else "–"
        voeding_subtag_bg, voeding_subtag_kleur = "#f0fdf4", "#166534"
    elif heeft_borst and heeft_fles:
        voeding_tag = f"{aantal_borst}x borst · {totaal_ml:.0f} ml fles"
        voeding_subtag_bg, voeding_subtag_kleur = "#f0fdf4", "#166534"
    else:
        voeding_tag = "–"
        voeding_subtag_bg, voeding_subtag_kleur = "#f0fdf4", "#166534"

    if heeft_borst and heeft_fles:
        with k2.container(border=True):
            st.markdown(f"""
<div style="opacity:{kaart_opacity};">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
  <div style="display:flex;align-items:center;gap:6px;">
    <span style="font-size:16px;">🍼</span>
    <span style="font-weight:700;font-size:13px;">Voeding</span>
  </div>
  <span style="font-size:11px;color:#aaa;">{"laatste " + laatste_voeding if laatste_voeding else ""}</span>
</div>
<div style="font-size:34px;font-weight:800;letter-spacing:-1px;line-height:1;margin:4px 0 2px;">{aantal_voeding}</div>
<div style="font-size:11px;color:#aaa;margin-bottom:10px;">voedingen vandaag</div>
<div style="padding-bottom:10px;display:flex;gap:6px;flex-wrap:wrap;">
  <span style="background:#fdf4ff;color:#7c3aed;font-size:11px;font-weight:700;padding:3px 8px;border-radius:99px;">{aantal_borst}x borst</span>
  <span style="background:#f0fdf4;color:#166534;font-size:11px;font-weight:700;padding:3px 8px;border-radius:99px;">{totaal_ml:.0f} ml fles</span>
</div>
</div>
""", unsafe_allow_html=True)
    else:
        dash_kaart(k2, "🍼", "Voeding",
                   aantal_voeding, "voedingen vandaag",
                   voeding_tag,
                   voeding_subtag_bg, voeding_subtag_kleur,
                   laatste=f"laatste {laatste_voeding}" if laatste_voeding else None)

    with k3.container(border=True):
        st.markdown(f"""
<div style="opacity:{kaart_opacity};">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
  <div style="display:flex;align-items:center;gap:6px;">
    <span style="font-size:16px;">🧷</span>
    <span style="font-weight:700;font-size:13px;">Luiers</span>
  </div>
  <span style="font-size:11px;color:#aaa;">{"laatste " + laatste_luier if laatste_luier else ""}</span>
</div>
<div style="display:flex;gap:16px;margin:4px 0 2px;">
  <div>
    <div style="font-size:34px;font-weight:800;letter-spacing:-1px;line-height:1;">{nat_count}</div>
    <div style="font-size:11px;color:#aaa;">nat</div>
  </div>
  <div style="width:1px;background:#aaa;opacity:0.3;margin:4px 0;"></div>
  <div>
    <div style="font-size:34px;font-weight:800;letter-spacing:-1px;line-height:1;">{vuil_count}</div>
    <div style="font-size:11px;color:#aaa;">vuil</div>
  </div>
</div>
<div style="padding-bottom:10px;margin-top:10px;">
  <span style="background:#fdf4ff;color:#7c3aed;font-size:11px;font-weight:700;padding:3px 8px;border-radius:99px;">{nat_count + vuil_count} totaal</span>
</div>
</div>
""", unsafe_allow_html=True)

    dash_kaart(k4, "🎈", "Activiteiten",
               aantal_act, "vandaag",
               laatste_act_naam if laatste_act_naam != '–' else "–",
               "#fff7ed", "#c2410c",
               laatste=f"{laatste_act_tijd}" if laatste_act_tijd else None)


    if gez_datum:
        with st.container(border=True):
            st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
  <div style="display:flex;align-items:center;gap:6px;">
    <span style="font-size:16px;">🩺</span>
    <span style="font-weight:700;font-size:13px;">Gezondheid</span>
  </div>
  <span style="font-size:11px;color:#aaa;">meting {gez_datum}</span>
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
""", unsafe_allow_html=True)

    if inst.get('opvangdagen_aan', 'nee') == 'ja' or timeline_html:
        with st.container(border=True):
            st.markdown(f"""<div style="font-weight:700;font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:14px;">Dagoverzicht</div>""", unsafe_allow_html=True)

            # Opvangdag bovenaan tijdlijn
            if inst.get('opvangdagen_aan', 'nee') == 'ja':
                if dag_is_opvang:
                    st.markdown("""
<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
  <div style="width:28px;height:28px;border-radius:50%;background:#FFF3CD;display:flex;align-items:center;justify-content:center;font-size:13px;flex-shrink:0;">🏠</div>
  <div style="flex:1;font-size:13px;font-weight:500;color:#633806;">Opvang- of oppassdag</div>
</div>""", unsafe_allow_html=True)
                    if st.button("Markering opheffen", key="ophef_opvang", help="Zet deze dag terug als thuisdag"):
                        verwijder_opvangdag(vandaag)
                        st.rerun()
                else:
                    if st.button("🏠 Opvangdag markeren", key="markeer_opvang",
                                 help="Markeer deze dag als opvang- of oppassdag. De dag telt dan niet mee in gemiddelden."):
                        markeer_opvangdag(vandaag)
                        st.rerun()

            if timeline_html:
                st.markdown(timeline_html, unsafe_allow_html=True)
            elif inst.get('opvangdagen_aan', 'nee') != 'ja':
                st.caption("Nog geen activiteit geregistreerd vandaag")
    else:
        with st.container(border=True):
            st.caption("Nog geen activiteit geregistreerd vandaag")

# ------------------------------
# TAB: Slaap
# ------------------------------
if selected_tab == "Slaap":
    st.title("Slaap toevoegen")
    st.caption("Registreer een slaapje met starttijd en kies tussen eindtijd of duur. De totale slaaptijd wordt automatisch berekend en meegenomen in het dagoverzicht.")
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Datum", value=datetime.now(TZ).date(), key="slaap_datum")
    with col2:
        start_time = st.time_input("Starttijd", value=datetime.now(TZ).replace(tzinfo=None).time(), key="slaap_tijd")

    invoer_modus = st.segmented_control("Invoer via", ["Duur", "Eindtijd"], default="Duur", key="slaap_invoer_modus", label_visibility="collapsed")
    start_dt_preview = get_device_datetime(start_time, start_date)

    if invoer_modus == "Duur":
        duur = st.number_input("Duur (minuten)", min_value=0, value=int(inst.get('slaap_default_duur', 60)), key="slaap_duur_input")
        eind_preview = (start_dt_preview + timedelta(minutes=duur)).strftime('%H:%M')
        st.caption(f"Eindtijd: **{eind_preview}**")
    else:
        eind_time = st.time_input("Eindtijd", value=(start_dt_preview + timedelta(minutes=int(inst.get('slaap_default_duur', 60)))).time(), key="slaap_eind_input")
        eind_dt_preview = get_device_datetime(eind_time, start_date)
        verschil = (eind_dt_preview - start_dt_preview).total_seconds() / 60
        if verschil < 0:
            verschil += 1440
        duur = int(verschil)
        st.caption(f"Duur: **{duur} minuten**")

    opm = st.text_input("Opmerking")
    if st.button("💾 Opslaan"):
        start_dt = get_device_datetime(start_time, start_date)
        end_dt = start_dt + timedelta(minutes=duur)
        ok = add_record(
            "Slaap",
            [start_dt.strftime("%Y-%m-%d %H:%M"), end_dt.strftime("%Y-%m-%d %H:%M"), duur, opm, '', '', '', '', '', '', '', '', '', '']
        )
        if ok:
            st.success("Slaap opgeslagen ✅")
            st.cache_data.clear()

# ------------------------------
# TAB: Voeding
# ------------------------------
if selected_tab == "Voeding":
    st.title("Voeding toevoegen")

    voeding_stijl   = inst.get('voeding_stijl', 'fles')
    hapjes_aan      = inst.get('hapjes_aan', 'nee') == 'ja'
    kolven_aan      = inst.get('kolven_aan', 'nee') == 'ja'
    kunstvoeding_productnaam = inst.get('kunstvoeding_productnaam', 'Kunstvoeding')

    toon_borst = voeding_stijl in ('borst', 'beiden')
    toon_fles  = voeding_stijl in ('fles', 'beiden')

    if st.session_state.get('voeding_opgeslagen'):
        msg = st.session_state.pop('voeding_opgeslagen')
        st.success(msg)
        info = st.session_state.pop('voeding_info', None)
        if info:
            st.caption(info)

    def sla_voeding_op(tijdstip, hoeveelheid, borst, kolven, fles, voeding_type, hapje_type, opm, is_kolven=False, datum=None):
        start_dt = get_device_datetime(tijdstip, datum).strftime('%Y-%m-%d %H:%M')
        ok = add_record(
            'Voeding',
            [start_dt, '', hoeveelheid if not is_kolven else '', opm, '', borst, kolven if is_kolven else '', fles, voeding_type, hapje_type, '', '', ''],
            rerun=False
        )
        if ok:
            voorraad_info = None
            if voeding_type == 'Fles' and fles == 'kunstvoeding' and hoeveelheid > 0:
                gram_per_schep = float(inst.get('kunstvoeding_gram_per_schep', 4.4))
                STANDAARD_FLESSEN = [(30, 1),(65, 2), (100, 3), (135, 4), (165, 5), (200, 6)]
                scheppen = next((s for eindvol, s in STANDAARD_FLESSEN if eindvol >= hoeveelheid), STANDAARD_FLESSEN[-1][1])
                gram = round(scheppen * gram_per_schep, 1)
                update_voorraad(kunstvoeding_productnaam, -gram)
                voorraad_info = f"🍼 {scheppen} scheppen = {gram}g kunstvoeding afgetrokken van voorraad"
            return True, voorraad_info
        return False, None

    if not toon_borst and not toon_fles:
        st.warning("Geen voedingstype ingeschakeld. Ga naar Instellingen → Voeding om dit in te stellen.")
    else:
        if toon_borst:
            with st.container(border=True):
                st.markdown("**Borstvoeding**")
                col1, col2, col3 = st.columns(3)
                with col1:
                    borst_datum = st.date_input('Datum', value=datetime.now(TZ).date(), key='borst_datum')
                with col2:
                    borst_tijd = st.time_input('Tijdstip', datetime.now(TZ).replace(tzinfo=None).time(), key='borst_tijd')
                with col3:
                    borst_kant = st.segmented_control('Borst', ['Links', 'Rechts', 'Beide'], default='Links', key='borst_kant')
                borst_duur = st.number_input('Duur (minuten)', min_value=0, value=10, key='borst_duur')
                borst_opm = st.text_input('Opmerking', key='borst_opm')
                if st.button("Opslaan", key='borst_opslaan'):
                    ok, info = sla_voeding_op(borst_tijd, borst_duur, borst_kant, '', '', 'Borst', '', borst_opm, datum=borst_datum)
                    if ok:
                        st.cache_data.clear()
                        st.session_state['voeding_opgeslagen'] = "Borstvoeding opgeslagen ✅"
                        st.rerun()

        if toon_fles:
            with st.container(border=True):
                pill_opties = ["Fles"] + (["Hapje"] if hapjes_aan else [])
                st.markdown("**Flesvoeding**" if not hapjes_aan else "**Fles / Hapje**")
                fles_type_keuze = st.pills("Type", pill_opties, key='fles_type_pills', default="Fles") if hapjes_aan else "Fles"
                col1, col2, col3 = st.columns(3)
                with col1:
                    fles_datum = st.date_input('Datum', value=datetime.now(TZ).date(), key='fles_datum')
                with col2:
                    fles_tijd = st.time_input('Tijdstip', datetime.now(TZ).replace(tzinfo=None).time(), key='fles_tijd')
                if fles_type_keuze == 'Fles':
                    fles_types = ['melk', 'kunstvoeding']
                    fles_default = inst.get('voeding_default_flestype', 'kunstvoeding') if inst.get('voeding_default_flestype', 'kunstvoeding') in ['melk', 'kunstvoeding'] else 'kunstvoeding'
                    with col3:
                        fles_inhoud = st.segmented_control('Type', fles_types, default=fles_default, key='fles_inhoud')
                    fles_ml = st.number_input('Hoeveelheid (ml)', min_value=0, value=int(inst.get('voeding_default_ml', 100)), key='fles_ml')
                    fles_opm = st.text_input('Opmerking', key='fles_opm')
                    if st.button("Opslaan", key='fles_opslaan'):
                        ok, info = sla_voeding_op(fles_tijd, fles_ml, '', '', fles_inhoud or fles_default, 'Fles', '', fles_opm, datum=fles_datum)
                        if ok:
                            st.cache_data.clear()
                            st.session_state['voeding_opgeslagen'] = "Fles opgeslagen ✅"
                            if info:
                                st.session_state['voeding_info'] = info
                            st.rerun()
                else:
                    with col3:
                        hapje_soort = st.pills('Type hapje', ['groente', 'fruit', 'snack'], default='groente', key='hapje_soort')
                    hapje_gram = st.number_input('Hoeveelheid (gram)', min_value=0, value=int(inst.get('voeding_default_hapje_gram', 50)), key='hapje_gram')
                    hapje_opm = st.text_input('Opmerking', key='hapje_opm')
                    if st.button("Opslaan", key='hapje_opslaan'):
                        ok, info = sla_voeding_op(fles_tijd, hapje_gram, '', '', '', 'Hapje', hapje_soort or 'groente', hapje_opm, datum=fles_datum)
                        if ok:
                            st.cache_data.clear()
                            st.session_state['voeding_opgeslagen'] = "Hapje opgeslagen ✅"
                            st.rerun()

        if kolven_aan:
            with st.container(border=True):
                st.markdown("**Kolven**")
                st.caption("Kolven telt niet mee als voeding op het dashboard.")
                col1, col2, col3 = st.columns(3)
                with col1:
                    kolven_datum = st.date_input('Datum', value=datetime.now(TZ).date(), key='kolven_datum')
                with col2:
                    kolven_tijd = st.time_input('Tijdstip', datetime.now(TZ).replace(tzinfo=None).time(), key='kolven_tijd')
                with col3:
                    kolven_kant = st.segmented_control('Borst', ['Links', 'Rechts', 'Beide'], default='Links', key='kolven_kant')
                kolven_ml = st.number_input('Hoeveelheid (ml)', min_value=0, value=int(inst.get('voeding_default_kolven_ml', 10)), key='kolven_ml')
                kolven_opm = st.text_input('Opmerking', key='kolven_opm')
                if st.button("Opslaan", key='kolven_opslaan'):
                    ok, info = sla_voeding_op(kolven_tijd, 0, kolven_kant, kolven_ml, '', 'Kolven', '', kolven_opm, is_kolven=True, datum=kolven_datum)
                    if ok:
                        st.cache_data.clear()
                        st.session_state['voeding_opgeslagen'] = "Kolven opgeslagen ✅"
                        st.rerun()

# ------------------------------
# TAB: Luiers
# ------------------------------
if selected_tab == "Luiers":
    st.title("Luiers toevoegen")
    st.caption("Registreer een luierwissel. Als 'Luiers' in je voorraad staat, wordt de voorraad automatisch bijgewerkt.")
    col1, col2 = st.columns(2)
    with col1:
        luier_datum = st.date_input("Datum", value=datetime.now(TZ).date(), key="luier_datum")
    with col2:
        tijdstip = st.time_input("Tijdstip", value=datetime.now(TZ).replace(tzinfo=None).time(), key="luier_tijd")
    luier_types = ["Nat", "Vuil"]
    luier_default = inst.get('luier_default_type', 'Nat') if inst.get('luier_default_type', 'Nat') in luier_types else 'Nat'
    typ = st.segmented_control("Type luier", luier_types, default=luier_default, key="luier_type_seg")
    opm = st.text_input("Opmerking")
    if st.button("💾 Opslaan"):
        if not typ:
            st.warning("Kies een type luier")
        else:
            start_dt = get_device_datetime(tijdstip, luier_datum)
            ok = add_record("Luier", [start_dt.strftime("%Y-%m-%d %H:%M"), '', '', opm, typ, '', '', '', '', '', '', '', ''])
            if ok:
                update_voorraad("Luiers", -1)
                st.success("Luier opgeslagen ✅")
                st.cache_data.clear()

# ------------------------------
# TAB: Gezondheid
# ------------------------------
if selected_tab == "Gezondheid":
    st.title("Gezondheid toevoegen")
    st.caption("Leg metingen vast. Laat velden leeg die je niet wilt invullen.")
    gez_datum_input = st.date_input("Datum meting", value=datetime.now(TZ).date(), key="gez_datum")
    col1, col2, col3 = st.columns(3)
    with col1:
        gewicht_raw = st.number_input("Gewicht (kg)", min_value=0.0, step=0.1,
                                      value=float(inst.get('gezondheid_default_gewicht', 0.0)),
                                      help="Laat op 0 staan om niet op te slaan")
        gewicht = gewicht_raw if gewicht_raw > 0 else None
    with col2:
        lengte_raw = st.number_input("Lengte (cm)", min_value=0.0, step=0.1,
                                     value=float(inst.get('gezondheid_default_lengte', 0.0)),
                                     help="Laat op 0 staan om niet op te slaan")
        lengte = lengte_raw if lengte_raw > 0 else None
    with col3:
        temp_raw = st.number_input("Temperatuur (°C)", min_value=0.0, max_value=45.0, step=0.1,
                                   value=float(inst.get('gezondheid_default_temp', 0.0)),
                                   help="Laat op 0 staan om niet op te slaan")
        temp = temp_raw if temp_raw > 0 else None
    opm = st.text_area("Opmerkingen / ziekten")
    if st.button("💾 Opslaan"):
        if not gewicht and not lengte and not temp and not opm:
            st.warning("Vul minimaal één waarde in")
        else:
            start_dt = datetime.combine(gez_datum_input, datetime.now(TZ).replace(tzinfo=None).time())
            ok = add_record("Gezondheid", [start_dt.strftime("%Y-%m-%d %H:%M"), '', '', '', '', '', '', '', '', '', gewicht, lengte, temp, opm])
            if ok:
                st.success("Gezondheid opgeslagen ✅")
                st.cache_data.clear()

# ------------------------------
# TAB: Activiteiten
# ------------------------------
if selected_tab == "Activiteiten":
    st.title("Activiteiten toevoegen")
    st.caption("Registreer wat jullie hebben gedaan en hoe de baby reageerde.")

    ACTIVITEITEN_STANDAARD = [
        ("🐛", "Tummy time"), ("🛁", "Bad"), ("🚿", "Douchen"),
        ("🚶", "Wandelen"), ("🏊", "Zwemmen"), ("👨‍👩‍👧", "Familie/vrienden"),
        ("🏥", "CJG/Dokter"), ("🧸", "Speelmat"), ("🧣", "Draagdoek"),
    ]
    extra_raw = inst.get('eigen_activiteiten', '')
    eigen_activiteiten = parse_eigen_activiteiten(extra_raw)
    ACTIVITEITEN = ACTIVITEITEN_STANDAARD + [(item["icon"], item["naam"]) for item in eigen_activiteiten]

    REACTIE_LABELS = ["Boos", "Huilerig", "Neutraal", "Blij", "Heel blij"]

    pill_opties = [f"{icon} {naam}" for icon, naam in ACTIVITEITEN]
    activiteit_pill = st.pills("Activiteit", pill_opties, key="act_pills")
    activiteit_naam = activiteit_pill.split(" ", 1)[1] if activiteit_pill else None

    col1, col2, col3 = st.columns(3)
    with col1:
        act_datum = st.date_input("Datum", value=datetime.now(TZ).date(), key="act_datum")
    with col2:
        tijdstip = st.time_input("Tijdstip", datetime.now(TZ).replace(tzinfo=None).time(), key="act_tijd")
    with col3:
        duur = st.number_input("Duur (minuten)", min_value=0, value=int(inst.get('activiteit_default_duur', 15)), key="act_duur")

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
            start_dt = get_device_datetime(tijdstip, act_datum)
            end_dt = start_dt + timedelta(minutes=duur)
            succes = add_activiteit(
                start_dt.strftime("%Y-%m-%d %H:%M"),
                end_dt.strftime("%Y-%m-%d %H:%M"),
                duur, activiteit_naam, reactie, opm
            )
            if succes:
                st.success("Activiteit opgeslagen ✅")
                st.cache_data.clear()


# ------------------------------
# TAB: Voorraad
# (ongewijzigd t.o.v. origineel)
# ------------------------------
if selected_tab == "Voorraad":

    STANDAARD_FLESSEN = [(30, 1), (65, 2), (100, 3), (135, 4), (165, 5), (200, 6)]
    gram_per_schep = float(inst.get('kunstvoeding_gram_per_schep', 4.4))

    def bereken_stats(naam, eenheid, actueel):
        per_dag = None
        dagen_resterend = None
        history = []
        kunstvoeding_prod = inst.get('kunstvoeding_productnaam', 'Kunstvoeding')
        if naam == kunstvoeding_prod and not baby_records.empty:
            for d in range(6, -1, -1):
                dag = datetime.now(TZ).date() - timedelta(days=d)
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
                dag = datetime.now(TZ).date() - timedelta(days=d)
                dag_df = baby_records[
                    (baby_records['Type'] == 'Luier') &
                    (baby_records['Starttijd'].dt.date == dag)
                ]
                history.append(len(dag_df))
            totaal = sum(history)
            if totaal > 0:
                per_dag = round(totaal / 7, 1)
                dagen_resterend = int(actueel / per_dag)
        elif not gebruik_logs.empty and 'Productnaam' in gebruik_logs.columns:
            prod_logs = gebruik_logs[gebruik_logs['Productnaam'] == naam].copy()
            if not prod_logs.empty:
                for d in range(6, -1, -1):
                    dag = datetime.now(TZ).date() - timedelta(days=d)
                    dag_gebruik = prod_logs[prod_logs['Datum'].dt.date == dag]['Hoeveelheid'].sum()
                    history.append(round(float(dag_gebruik), 1))
                totaal = sum(history)
                if totaal > 0:
                    per_dag = round(totaal / 7, 1)
                    if per_dag > 0:
                        dagen_resterend = int(actueel / per_dag)
        return per_dag, dagen_resterend, history

    def log_bijvulling(productnaam, hoeveelheid):
        try:
            supabase.table("voorraad_bijvulling").insert({
                "user_id": user_id,
                "datum": datetime.now(TZ).replace(tzinfo=None).strftime('%Y-%m-%d %H:%M'),
                "productnaam": productnaam,
                "hoeveelheid": hoeveelheid,
            }).execute()
        except Exception as e:
            st.error(f"Kon bijvulling niet loggen: {e}")

    handmatig_raw = inst.get('handmatige_producten', '[]')
    try:
        handmatig_lijst = json.loads(handmatig_raw)
    except Exception:
        handmatig_lijst = []

    st.title("Voorraad")

    if voorraad.empty:
        st.info("Je hebt nog geen voorraadproducten ingesteld.")
        with st.container(border=True):
            st.markdown("**➕ Eerste product toevoegen**")
            np1, np2, np3, np4 = st.columns([3, 2, 2, 2])
            with np1:
                nieuw_prod_naam = st.text_input('Productnaam', key='eerste_prod_naam', placeholder='bijv. Kunstvoeding')
            with np2:
                nieuw_prod_variant = st.text_input('Variant', key='eerste_prod_variant', placeholder='bijv. Maat 2')
            with np3:
                nieuw_prod_eenheid = st.text_input('Eenheid', key='eerste_prod_eenheid', placeholder='bijv. Gram, Stuks')
            with np4:
                nieuw_prod_min = st.number_input('Minimum voorraad', min_value=0.0, step=1.0, key='eerste_prod_min')
            nieuw_prod_actueel = st.number_input('Huidige voorraad', min_value=0.0, step=1.0, key='eerste_prod_actueel')
            if st.button("➕ Product toevoegen", key='add_eerste_prod', use_container_width=True):
                if nieuw_prod_naam:
                    try:
                        supabase.table("voorraad").insert({
                            "user_id": user_id,
                            "productnaam": nieuw_prod_naam,
                            "variant": nieuw_prod_variant,
                            "eenheid": nieuw_prod_eenheid or 'stuks',
                            "actuele_voorraad": nieuw_prod_actueel,
                            "minimum_voorraad": nieuw_prod_min,
                        }).execute()
                        st.success(f"{nieuw_prod_naam} toegevoegd ✅")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Kon product niet toevoegen: {e}")
                else:
                    st.warning("Vul een productnaam in")
    else:
        lage_items_html = ""
        for _, r in voorraad.iterrows():
            actueel_a = pd.to_numeric(r.get('Actuele voorraad', 0), errors='coerce') or 0
            minimum_a = pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0
            if minimum_a > 0 and actueel_a <= minimum_a * 1.2:
                naam_a   = r.get('Productnaam', 'Onbekend')
                eenheid_a = r.get('Eenheid', 'stuks')
                _, dagen_r, _ = bereken_stats(naam_a, eenheid_a, actueel_a)
                dagen_str_a = f", genoeg voor ±{dagen_r} dagen" if dagen_r is not None else ""
                lage_items_html += f'<div style="font-size:12px;color:#b42318;margin-top:2px;">{naam_a} — nog {actueel_a:.0f} {eenheid_a}{dagen_str_a}</div>'
        if lage_items_html:
            st.markdown(f"""
<div style="background:#fef3f2;border:1px solid #fecdca;border-radius:14px;padding:12px 16px;margin-bottom:16px;display:flex;gap:10px;align-items:flex-start;">
  <span style="font-size:18px;">⚠️</span>
  <div>
    <div style="font-weight:700;font-size:13px;color:#b42318;margin-bottom:2px;">Lage voorraad</div>
    {lage_items_html}
  </div>
</div>""", unsafe_allow_html=True)

        auto_producten     = [r for _, r in voorraad.iterrows() if r.get('Productnaam', '') not in handmatig_lijst]
        handmatig_prod_rij = [r for _, r in voorraad.iterrows() if r.get('Productnaam', '') in handmatig_lijst]

        def render_product_rij(r, sectie_prefix):
            naam      = r.get('Productnaam', 'Onbekend')
            variant   = r.get('Variant', '') or ''
            eenheid   = r.get('Eenheid', 'stuks')
            actueel   = pd.to_numeric(r.get('Actuele voorraad', 0), errors='coerce') or 0
            minimum   = pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0
            handmatig = naam in handmatig_lijst
            per_dag, dagen_resterend, _ = bereken_stats(naam, eenheid, actueel)
            is_laag    = minimum > 0 and actueel <= minimum
            is_waarsch = not is_laag and minimum > 0 and actueel <= minimum * 1.2
            if is_laag:
                status_icon = "🔴"; status_label = "Laag"
            elif is_waarsch:
                status_icon = "🟠"; status_label = "Let op"
            else:
                status_icon = "🟢"; status_label = "Voldoende"
            dagen_str   = f"±{dagen_resterend} dagen" if dagen_resterend is not None else "–"
            per_dag_str = f"~{per_dag} {eenheid}/dag" if per_dag is not None else ""
            titel_str   = f"{naam} · {variant}" if variant else naam
            sleutel_bijvul  = f"toon_bijvul_{sectie_prefix}_{naam}"
            sleutel_gebruik = f"toon_gebruik_{sectie_prefix}_{naam}"

            with st.container(border=True):
                kop1, kop2 = st.columns([5, 1])
                with kop1:
                    st.markdown(f"**{titel_str}**")
                with kop2:
                    st.markdown(f"<div style='text-align:right;font-size:13px;'>{status_icon} {status_label}</div>", unsafe_allow_html=True)
                sc1, sc2, sc3 = st.columns(3)
                dagen_kleur = "#e74c3c" if is_laag else ("#e67e22" if is_waarsch else "inherit")
                sc1.caption("Voorraad"); sc1.markdown(f"**{actueel:.0f}** {eenheid}")
                sc2.caption("Gemiddeld/dag"); sc2.markdown(f"**{f'~{per_dag}' if per_dag is not None else '–'}** {eenheid if per_dag is not None else ''}")
                sc3.caption("Nog genoeg voor"); sc3.markdown(f"<span style='font-weight:700;color:{dagen_kleur};'>{dagen_str}</span>", unsafe_allow_html=True)

                if handmatig:
                    bk1, bk2, bk3 = st.columns([1, 1, 4])
                    with bk1:
                        if st.button("− Gebruik", key=f"btn_gebruik_{sectie_prefix}_{naam}", use_container_width=True):
                            st.session_state[sleutel_gebruik] = not st.session_state.get(sleutel_gebruik, False)
                            st.session_state[sleutel_bijvul] = False
                    with bk2:
                        if st.button("＋ Bijvullen", key=f"btn_bijvul_{sectie_prefix}_{naam}", use_container_width=True):
                            st.session_state[sleutel_bijvul] = not st.session_state.get(sleutel_bijvul, False)
                            st.session_state[sleutel_gebruik] = False
                else:
                    bk1, bk2 = st.columns([1, 5])
                    with bk1:
                        if st.button("＋ Bijvullen", key=f"btn_bijvul_{sectie_prefix}_{naam}", use_container_width=True):
                            st.session_state[sleutel_bijvul] = not st.session_state.get(sleutel_bijvul, False)

                if st.session_state.get(sleutel_bijvul, False):
                    st.divider()
                    snelkeuze_raw = inst.get(f'snelkeuze_{naam}', '')
                    try:
                        snelkeuze_opties = json.loads(snelkeuze_raw) if snelkeuze_raw else []
                    except Exception:
                        snelkeuze_opties = []
                    if snelkeuze_opties:
                        st.caption("Snelkeuzes")
                        chip_cols = st.columns(min(len(snelkeuze_opties), 4))
                        for j, optie in enumerate(snelkeuze_opties[:4]):
                            with chip_cols[j]:
                                if st.button(f"＋ {optie.get('label','')}", key=f"chip_{sectie_prefix}_{naam}_{j}", use_container_width=True):
                                    update_voorraad(naam, float(optie.get('waarde', 0)))
                                    log_bijvulling(naam, optie.get('waarde', 0))
                                    st.toast(f"{naam} bijgevuld ✅")
                                    st.session_state[sleutel_bijvul] = False
                                    st.cache_data.clear()
                                    st.rerun()
                    bc1, bc2 = st.columns([3, 1])
                    with bc1:
                        bijvul_val = st.number_input(f"Hoeveelheid bijvullen ({eenheid})", min_value=0.0, step=1.0, value=1.0, key=f"bijvul_val_{sectie_prefix}_{naam}")
                    with bc2:
                        st.write("")
                        if st.button("Opslaan", key=f"bijvul_opslaan_{sectie_prefix}_{naam}", use_container_width=True, type="primary"):
                            update_voorraad(naam, bijvul_val)
                            log_bijvulling(naam, bijvul_val)
                            st.toast(f"{naam} bijgevuld met {bijvul_val:.0f} {eenheid} ✅")
                            st.session_state[sleutel_bijvul] = False
                            st.cache_data.clear()
                            st.rerun()
                    cc1, cc2 = st.columns([3, 1])
                    with cc1:
                        corr_val = st.number_input(f"Corrigeer voorraad naar ({eenheid})", min_value=0.0, step=1.0, value=float(actueel), key=f"corr_val_{sectie_prefix}_{naam}")
                    with cc2:
                        st.write("")
                        if st.button("Corrigeer", key=f"corr_opslaan_{sectie_prefix}_{naam}", use_container_width=True):
                            verschil = corr_val - float(actueel)
                            if verschil != 0:
                                update_voorraad(naam, verschil)
                                log_bijvulling(f"{naam} (correctie)", verschil)
                                st.toast(f"{naam} gecorrigeerd naar {corr_val:.0f} {eenheid} ✅")
                                st.session_state[sleutel_bijvul] = False
                                st.cache_data.clear()
                                st.rerun()

                if handmatig and st.session_state.get(sleutel_gebruik, False):
                    st.divider()
                    vandaag_gebruik = 0
                    if not gebruik_logs.empty and 'Productnaam' in gebruik_logs.columns:
                        vandaag_gebruik = int(gebruik_logs[
                            (gebruik_logs['Productnaam'] == naam) &
                            (gebruik_logs['Datum'].dt.date == datetime.now(TZ).date())
                        ]['Hoeveelheid'].sum())
                    gc1, gc2, gc3 = st.columns([3, 1, 1])
                    with gc1:
                        gebruik_val = st.number_input(f"Hoeveel {eenheid} aftrekken?", min_value=0.1, step=1.0, value=1.0, key=f"gebruik_val_{sectie_prefix}_{naam}")
                    with gc2:
                        st.write("")
                        if st.button("Aftrekken", key=f"gebruik_opslaan_{sectie_prefix}_{naam}", use_container_width=True):
                            update_voorraad(naam, -gebruik_val)
                            log_gebruik(naam, gebruik_val)
                            st.toast(f"{naam}: −{gebruik_val:.0f} geregistreerd ✅")
                            st.session_state[sleutel_gebruik] = False
                            st.cache_data.clear()
                            st.rerun()
                    with gc3:
                        st.metric("Vandaag", vandaag_gebruik)

        if auto_producten:
            st.caption("⚡ Automatisch bijgehouden")
            for r in auto_producten:
                render_product_rij(r, "auto")
        if handmatig_prod_rij:
            st.caption("🖐 Handmatig bijhouden")
            for r in handmatig_prod_rij:
                render_product_rij(r, "hand")

        st.caption("Schatting op basis van gemiddeld verbruik afgelopen 7 dagen.")
        st.divider()
        with st.expander("📋 Bijvulhistorie"):
            if not bijvullingen.empty:
                bv_df = bijvullingen.copy()
                bv_df['Datum'] = pd.to_datetime(bv_df['Datum'], errors='coerce')
                bv_df = bv_df.dropna(subset=['Datum']).sort_values('Datum', ascending=False).head(20)
                for _, row in bv_df.iterrows():
                    datum_str_bv = row['Datum'].strftime('%d %b %H:%M')
                    prod_bv  = row.get('Productnaam', '')
                    hoev_bv  = row.get('Hoeveelheid', '')
                    is_cor   = '(correctie)' in str(prod_bv)
                    kleur_bv = "#888" if is_cor else "#7a9e72"
                    teken_bv = "±" if is_cor else "+"
                    st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #f5f5f5;">
  <span style="font-size:12px;color:#bbb;width:100px;">{datum_str_bv}</span>
  <span style="font-size:13px;font-weight:600;flex:1;">{prod_bv}</span>
  <span style="font-size:13px;font-weight:700;color:{kleur_bv};">{teken_bv}{hoev_bv}</span>
</div>""", unsafe_allow_html=True)
            else:
                st.info("Nog geen bijvullingen geregistreerd.")

        with st.expander("⚙️ Producten beheren"):
            st.caption("Pas variant, minimum of eenheid aan.")
            for _, r in voorraad.iterrows():
                prod_id       = r.get('id')
                prod_naam     = r.get('Productnaam', '')
                prod_eenheid  = r.get('Eenheid', 'stuks')
                prod_variant  = r.get('Variant', '') or ''
                prod_min      = float(pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0)
                prod_handmatig = prod_naam in handmatig_lijst
                bc1, bc2, bc3, bc4, bc5, bc6 = st.columns([2, 2, 1, 1, 1, 1])
                with bc1:
                    st.markdown(f'<div style="font-size:13px;font-weight:600;padding-top:8px;">{prod_naam}</div>', unsafe_allow_html=True)
                with bc2:
                    nieuw_variant = st.text_input('Variant', value=prod_variant, key=f'bh_variant_{prod_id}', label_visibility='collapsed', placeholder='bijv. Maat 2')
                with bc3:
                    nieuw_min = st.number_input('Min.', min_value=0.0, step=1.0, value=prod_min, key=f'bh_min_{prod_id}', label_visibility='collapsed')
                with bc4:
                    st.caption(f"{prod_eenheid}")
                with bc5:
                    nieuw_handmatig = st.toggle('Handmatig', value=prod_handmatig, key=f'bh_handmatig_{prod_id}')
                with bc6:
                    if st.button("💾", key=f'bh_save_{prod_id}'):
                        try:
                            supabase.table("voorraad").update({"minimum_voorraad": nieuw_min, "variant": nieuw_variant}).eq("id", str(prod_id)).eq("user_id", user_id).execute()
                            if nieuw_handmatig and prod_naam not in handmatig_lijst:
                                handmatig_lijst.append(prod_naam)
                            elif not nieuw_handmatig and prod_naam in handmatig_lijst:
                                handmatig_lijst.remove(prod_naam)
                            save_instelling('handmatige_producten', json.dumps(handmatig_lijst))
                            st.toast(f"{prod_naam} opgeslagen ✅")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fout: {e}")

            st.divider()
            st.markdown("**Nieuw product toevoegen**")
            np1, np2, np3, np4, np5, np6 = st.columns([3, 2, 1, 1, 1, 1])
            with np1:
                nieuw_prod_naam = st.text_input('Naam', key='nieuw_prod_naam', label_visibility='collapsed', placeholder='Productnaam')
            with np2:
                nieuw_prod_variant = st.text_input('Variant', key='nieuw_prod_variant', label_visibility='collapsed', placeholder='bijv. Maat 2')
            with np3:
                nieuw_prod_eenheid = st.text_input('Eenheid', key='nieuw_prod_eenheid', label_visibility='collapsed', placeholder='stuks')
            with np4:
                nieuw_prod_min = st.number_input('Min.', min_value=0.0, step=1.0, key='nieuw_prod_min', label_visibility='collapsed')
            with np5:
                nieuw_prod_handmatig = st.toggle('Handmatig', value=False, key='nieuw_prod_handmatig')
            with np6:
                if st.button("➕", key='add_prod'):
                    if nieuw_prod_naam:
                        try:
                            supabase.table("voorraad").insert({
                                "user_id": user_id, "productnaam": nieuw_prod_naam,
                                "variant": nieuw_prod_variant, "eenheid": nieuw_prod_eenheid or 'stuks',
                                "actuele_voorraad": 0, "minimum_voorraad": nieuw_prod_min,
                            }).execute()
                            if nieuw_prod_handmatig:
                                handmatig_lijst.append(nieuw_prod_naam)
                                save_instelling('handmatige_producten', json.dumps(handmatig_lijst))
                            st.toast(f"{nieuw_prod_naam} toegevoegd ✅")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fout: {e}")
                    else:
                        st.warning("Vul een productnaam in")

            st.divider()
            st.markdown("**Product verwijderen**")
            prod_namen_del = voorraad['Productnaam'].tolist()
            del1, del2 = st.columns([4, 1])
            with del1:
                prod_to_del = st.selectbox('Product', prod_namen_del, key='prod_del', label_visibility='collapsed')
            with del2:
                if st.button("🗑️ Verwijderen", key='del_prod', use_container_width=True):
                    st.session_state['confirm_delete_product'] = prod_to_del
            if st.session_state.get('confirm_delete_product') == prod_to_del:
                st.warning(f"Weet je zeker dat je **{prod_to_del}** wilt verwijderen?")
                dc1, dc2 = st.columns(2)
                with dc1:
                    if st.button("Ja, verwijderen", key="confirm_del_prod_yes", type="primary", use_container_width=True):
                        try:
                            supabase.table("voorraad").delete().eq("user_id", user_id).eq("productnaam", prod_to_del).execute()
                            if prod_to_del in handmatig_lijst:
                                handmatig_lijst.remove(prod_to_del)
                                save_instelling('handmatige_producten', json.dumps(handmatig_lijst))
                            st.toast(f"{prod_to_del} verwijderd")
                            st.session_state.pop('confirm_delete_product', None)
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fout: {e}")
                with dc2:
                    if st.button("Annuleren", key="confirm_del_prod_no", use_container_width=True):
                        st.session_state.pop('confirm_delete_product', None)
                        st.rerun()


# ------------------------------
# TAB: Bewerk records (ongewijzigd)
# ------------------------------
if selected_tab == "Bewerk records":
    st.title('Bewerk record')
    st.caption('Bewerk of verwijder records in de database om fouten te herstellen.')

    record_type = st.selectbox('Kies type record', ['Slaap', 'Voeding', 'Luier', 'Gezondheid', 'Activiteit'])

    if record_type == 'Activiteit':
        if activiteiten.empty:
            st.info('Geen activiteiten beschikbaar')
        else:
            act_sorted = activiteiten.sort_values('Starttijd', ascending=False)
            act_options = (act_sorted['Starttijd'].dt.strftime('%Y-%m-%d %H:%M') + ' — ' + act_sorted['Activiteit_type'].fillna('?')).tolist()
            selected = st.selectbox('Selecteer activiteit', act_options)
            if selected:
                selected_tijd = selected.split(' — ')[0]
                idx = activiteiten[activiteiten['Starttijd'].dt.strftime('%Y-%m-%d %H:%M') == selected_tijd].index[0]
                record = activiteiten.loc[idx]
                record_id = record['id']
                ACTIVITEITEN_STANDAARD_NAMEN = ["Tummy time", "Bad", "Douchen", "Wandelen", "Zwemmen", "Familie/vrienden", "CJG/Dokter", "Speelmat", "Draagdoek"]
                eigen_bew = parse_eigen_activiteiten(inst.get('eigen_activiteiten', '[]'))
                ACTIVITEITEN_NAMEN = ACTIVITEITEN_STANDAARD_NAMEN + [item["naam"] for item in eigen_bew]
                REACTIE_LABELS = ["Boos", "Huilerig", "Neutraal", "Blij", "Heel blij"]
                huidig_type = record.get('Activiteit_type', '')
                act_idx = ACTIVITEITEN_NAMEN.index(huidig_type) if huidig_type in ACTIVITEITEN_NAMEN else 0
                activiteit_type = st.selectbox('Activiteit', ACTIVITEITEN_NAMEN, index=act_idx)
                col1, col2, col3 = st.columns(3)
                with col1:
                    bew_datum = st.date_input('Datum', value=record['Starttijd'].date(), key='bew_act_datum')
                with col2:
                    tijdstip = st.time_input('Tijdstip', record['Starttijd'].time())
                with col3:
                    duur = st.number_input('Duur (minuten)', min_value=0, value=int(record.get('Duur', 15) or 15))
                reactie_idx = REACTIE_LABELS.index(record['Reactie']) if record.get('Reactie') in REACTIE_LABELS else 3
                reactie = st.selectbox('Reactie', REACTIE_LABELS, index=reactie_idx)
                opm = st.text_input('Opmerking', record.get('Opmerking', '') or '')
                col_save, col_del = st.columns([3, 1])
                with col_save:
                    if st.button('💾 Opslaan wijziging', use_container_width=True):
                        start_dt = get_device_datetime(tijdstip, bew_datum)
                        end_dt = start_dt + timedelta(minutes=duur)
                        try:
                            supabase.table("activiteiten").update({
                                "starttijd": start_dt.strftime('%Y-%m-%d %H:%M'),
                                "eindtijd": end_dt.strftime('%Y-%m-%d %H:%M'),
                                "duur": duur, "activiteit_type": activiteit_type,
                                "reactie": reactie, "opmerking": opm,
                            }).eq("id", record_id).eq("user_id", user_id).execute()
                            st.success('Activiteit aangepast ✅')
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"Kon niet updaten: {e}")
                with col_del:
                    if st.button('🗑️ Verwijderen', use_container_width=True, type='secondary'):
                        st.session_state['confirm_delete_act'] = record_id
                if st.session_state.get('confirm_delete_act') == record_id:
                    st.warning("Weet je zeker dat je deze activiteit wilt verwijderen?")
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if st.button("Ja, verwijderen", key="confirm_del_act_yes", type="primary", use_container_width=True):
                            try:
                                supabase.table("activiteiten").delete().eq("id", record_id).eq("user_id", user_id).execute()
                                st.success("Activiteit verwijderd ✅")
                                st.session_state.pop('confirm_delete_act', None)
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Kon niet verwijderen: {e}")
                    with cc2:
                        if st.button("Annuleren", key="confirm_del_act_no", use_container_width=True):
                            st.session_state.pop('confirm_delete_act', None)
                            st.rerun()
    else:
        df_type = baby_records[baby_records['Type'] == record_type].sort_values('Starttijd', ascending=False)
        if df_type.empty:
            st.info('Geen records beschikbaar')
        else:
            if record_type == 'Voeding':
                options = (df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M') + ' — ' + df_type['Voeding_type'].fillna('?')).tolist()
            elif record_type == 'Luier':
                options = (df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M') + ' — ' + df_type['Type Luier'].fillna('?')).tolist()
            else:
                options = df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M').tolist()
            selected = st.selectbox('Selecteer record', options)
            if selected:
                selected_tijd = selected.split(' — ')[0]
                idx = df_type[df_type['Starttijd'].dt.strftime('%Y-%m-%d %H:%M') == selected_tijd].index[0]
                record = df_type.loc[idx]
                record_id = record['id']

                if record_type == 'Slaap':
                    col1, col2 = st.columns(2)
                    with col1:
                        bew_datum = st.date_input('Datum', value=record['Starttijd'].date(), key='bew_slaap_datum')
                    with col2:
                        start = st.time_input('Starttijd', record['Starttijd'].time())
                    try:
                        eind_dt_bew = pd.to_datetime(record.get('Eindtijd'))
                        duur_berekend = int((eind_dt_bew - record['Starttijd']).total_seconds() / 60) if pd.notna(eind_dt_bew) else int(record.get('Hoeveelheid', 0) or 0)
                    except Exception:
                        duur_berekend = int(record.get('Hoeveelheid', 0) or 0)
                    duur = st.number_input('Duur (min)', value=max(0, duur_berekend), min_value=0)
                    opm = st.text_input('Opmerking', record.get('Opmerking', '') or '')
                    col_save, col_del = st.columns([3, 1])
                    with col_save:
                        if st.button('💾 Opslaan wijziging slaap', use_container_width=True):
                            start_dt = get_device_datetime(start, bew_datum)
                            eind_dt = start_dt + timedelta(minutes=duur)
                            edit_record(record_id, {"starttijd": start_dt.strftime('%Y-%m-%d %H:%M'), "eindtijd": eind_dt.strftime('%Y-%m-%d %H:%M'), "hoeveelheid": duur, "opmerking": opm})
                    with col_del:
                        if st.button('🗑️ Verwijderen', key='del_slaap', use_container_width=True, type='secondary'):
                            st.session_state['confirm_delete'] = record_id

                elif record_type == 'Voeding':
                    col1, col2 = st.columns(2)
                    with col1:
                        bew_datum = st.date_input('Datum', value=record['Starttijd'].date(), key='bew_voed_datum')
                    with col2:
                        start = st.time_input('Tijdstip', record['Starttijd'].time())
                    hoeveelheid = st.number_input('Hoeveelheid', value=int(record.get('Hoeveelheid', 0) or 0), min_value=0)
                    opm = st.text_input('Opmerking', record.get('Opmerking', '') or '')
                    col_save, col_del = st.columns([3, 1])
                    with col_save:
                        if st.button('💾 Opslaan wijziging voeding', use_container_width=True):
                            start_dt = get_device_datetime(start, bew_datum)
                            edit_record(record_id, {"starttijd": start_dt.strftime('%Y-%m-%d %H:%M'), "hoeveelheid": hoeveelheid, "opmerking": opm})
                    with col_del:
                        if st.button('🗑️ Verwijderen', key='del_voeding', use_container_width=True, type='secondary'):
                            st.session_state['confirm_delete'] = record_id

                elif record_type == 'Luier':
                    col1, col2 = st.columns(2)
                    with col1:
                        bew_datum = st.date_input('Datum', value=record['Starttijd'].date(), key='bew_luier_datum')
                    with col2:
                        start = st.time_input('Tijdstip', record['Starttijd'].time())
                    typ = st.segmented_control('Type luier', ['Nat', 'Vuil'], default=record.get('Type Luier', 'Nat') or 'Nat', key='bew_luier_type')
                    opm = st.text_input('Opmerking', record.get('Opmerking', '') or '')
                    col_save, col_del = st.columns([3, 1])
                    with col_save:
                        if st.button('💾 Opslaan wijziging luier', use_container_width=True):
                            start_dt = get_device_datetime(start, bew_datum)
                            edit_record(record_id, {"starttijd": start_dt.strftime('%Y-%m-%d %H:%M'), "opmerking": opm, "type_luier": typ})
                    with col_del:
                        if st.button('🗑️ Verwijderen', key='del_luier', use_container_width=True, type='secondary'):
                            st.session_state['confirm_delete'] = record_id

                elif record_type == 'Gezondheid':
                    bew_datum = st.date_input('Datum meting', value=record['Starttijd'].date(), key='bew_gez_datum')
                    gewicht = st.number_input('Gewicht (kg)', value=float(record.get('Gewicht', 0.0) or 0.0), min_value=0.0)
                    lengte = st.number_input('Lengte (cm)', value=float(record.get('Lengte', 0.0) or 0.0), min_value=0.0)
                    temp = st.number_input('Temperatuur (°C)', value=float(record.get('Temperatuur', 0.0) or 0.0), min_value=0.0)
                    opm = st.text_area('Opmerkingen / ziekten', record.get('Opmerkingen / ziekten', '') or '')
                    col_save, col_del = st.columns([3, 1])
                    with col_save:
                        if st.button('💾 Opslaan wijziging gezondheid', use_container_width=True):
                            start_dt = datetime.combine(bew_datum, record['Starttijd'].time())
                            edit_record(record_id, {"starttijd": start_dt.strftime('%Y-%m-%d %H:%M'), "gewicht": gewicht, "lengte": lengte, "temperatuur": temp, "opmerkingen": opm})
                    with col_del:
                        if st.button('🗑️ Verwijderen', key='del_gez', use_container_width=True, type='secondary'):
                            st.session_state['confirm_delete'] = record_id

                if st.session_state.get('confirm_delete') == record_id:
                    st.warning(f"Weet je zeker dat je dit {record_type.lower()}-record wilt verwijderen?")
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if st.button("Ja, verwijderen", key="confirm_del_yes", type="primary", use_container_width=True):
                            try:
                                supabase.table("baby_records").delete().eq("id", record_id).eq("user_id", user_id).execute()
                                st.success(f"{record_type} verwijderd ✅")
                                st.session_state.pop('confirm_delete', None)
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Kon niet verwijderen: {e}")
                    with cc2:
                        if st.button("Annuleren", key="confirm_del_no", use_container_width=True):
                            st.session_state.pop('confirm_delete', None)
                            st.rerun()


# ------------------------------
# TAB: Analyse
# GEWIJZIGD: opvangdagen worden uitgesloten van gemiddelden
# ------------------------------
if selected_tab == "Analyse":
    st.title("Analyse")

    def metric_row(cards):
        cols = st.columns(len(cards))
        for col, (label, value, sub) in zip(cols, cards):
            with col:
                with st.container(border=True):
                    st.metric(label=label, value=value, help=sub)

    if baby_records.empty:
        st.info("Geen gegevens beschikbaar voor analyse.")
    else:
        col_periode, col_filter = st.columns([3, 2])
        with col_periode:
            periode_opties = {"7 dagen": 7, "14 dagen": 14, "30 dagen": 30}
            periode_keuze = st.segmented_control(
                "Periode", list(periode_opties.keys()), default="14 dagen", label_visibility="collapsed"
            )
        with col_filter:
            # Toggle: opvangdagen uitsluiten
            opvang_uitsluiten = st.toggle(
                "Alleen thuisdagen",
                value=True,
                help="Opvang- en oppassdagen worden uitgesloten van gemiddelden en grafieken.",
                key="analyse_opvang_toggle"
            )

        dagen = periode_opties.get(periode_keuze, 14)
        cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=dagen)
        tz_aware = not baby_records.empty and baby_records['Starttijd'].dt.tz is not None
        if not tz_aware:
            cutoff = cutoff.tz_localize(None)

        rec        = baby_records[baby_records['Starttijd'] >= cutoff].copy()
        voeding_df = rec[rec['Type'] == 'Voeding'].copy()
        slaap_df   = rec[rec['Type'] == 'Slaap'].copy()
        luier_df   = rec[rec['Type'] == 'Luier'].copy()
        gezond_df  = baby_records[baby_records['Type'] == 'Gezondheid'].copy()
        act_df     = activiteiten[activiteiten['Starttijd'] >= cutoff].copy() if not activiteiten.empty else pd.DataFrame()

        if not slaap_df.empty:
            slaap_df['Eindtijd'] = pd.to_datetime(slaap_df['Eindtijd'], errors='coerce')
            slaap_df['Duur_min'] = ((slaap_df['Eindtijd'] - slaap_df['Starttijd']).dt.total_seconds() / 60).clip(lower=0)

        if not voeding_df.empty: voeding_df['Datum'] = voeding_df['Starttijd'].dt.date
        if not slaap_df.empty:   slaap_df['Datum']   = slaap_df['Starttijd'].dt.date
        if not luier_df.empty:   luier_df['Datum']   = luier_df['Starttijd'].dt.date
        if not act_df.empty:     act_df['Datum']     = act_df['Starttijd'].dt.date

        # Opvangdagen ophalen en filteren
        opvang_set = get_opvangdagen_set()

        # Bepaal alle dagen in de periode
        alle_dagen_in_periode = set()
        for i in range(dagen):
            d = (datetime.now(TZ) - timedelta(days=i)).date()
            alle_dagen_in_periode.add(d)

        opvangdagen_in_periode = opvang_set & alle_dagen_in_periode
        thuisdagen_in_periode  = alle_dagen_in_periode - opvang_set
        aantal_opvangdagen = len(opvangdagen_in_periode)
        aantal_thuisdagen  = len(thuisdagen_in_periode)

        # Filter dataframes als toggle aan staat
        if opvang_uitsluiten and opvang_set:
            voeding_df_gem = voeding_df[~voeding_df['Datum'].isin(opvang_set)] if not voeding_df.empty else voeding_df
            slaap_df_gem   = slaap_df[~slaap_df['Datum'].isin(opvang_set)]     if not slaap_df.empty   else slaap_df
            luier_df_gem   = luier_df[~luier_df['Datum'].isin(opvang_set)]     if not luier_df.empty   else luier_df
            act_df_gem     = act_df[~act_df['Datum'].isin(opvang_set)]         if not act_df.empty     else act_df
            teldagen = max(aantal_thuisdagen, 1)
            filter_label = f"{aantal_opvangdagen} opvangdag(en) uitgesloten"
        else:
            voeding_df_gem = voeding_df
            slaap_df_gem   = slaap_df
            luier_df_gem   = luier_df
            act_df_gem     = act_df
            teldagen = dagen
            filter_label = None

        if filter_label:
            st.caption(f"ℹ️ {filter_label}")

        voeding_fles_borst     = voeding_df[voeding_df['Voeding_type'].isin(['Borst', 'Fles'])]     if not voeding_df.empty     else pd.DataFrame()
        voeding_fles_borst_gem = voeding_df_gem[voeding_df_gem['Voeding_type'].isin(['Borst', 'Fles'])] if not voeding_df_gem.empty else pd.DataFrame()

        at1, at2, at3 = st.tabs(["Overzicht", "Trends", "Activiteiten"])

        # Gedeelde berekeningen op gefilterde data
        gem_voedingen = round(len(voeding_fles_borst_gem) / teldagen, 1) if not voeding_fles_borst_gem.empty else 0
        gem_ml        = round(voeding_fles_borst_gem['Hoeveelheid'].mean(), 0) if not voeding_fles_borst_gem.empty else 0
        gem_slaap_u   = round(slaap_df_gem.groupby('Datum')['Duur_min'].sum().mean() / 60, 1) if not slaap_df_gem.empty else 0
        gem_luiers    = round(len(luier_df_gem) / teldagen, 1) if not luier_df_gem.empty else 0
        nat_count     = len(luier_df_gem[luier_df_gem['Type Luier'] == 'Nat'])  if not luier_df_gem.empty else 0
        vuil_count    = len(luier_df_gem[luier_df_gem['Type Luier'] == 'Vuil']) if not luier_df_gem.empty else 0
        tot_l         = nat_count + vuil_count
        luier_sub     = f"{round(nat_count/tot_l*100)}% nat · {round(vuil_count/tot_l*100)}% vuil" if tot_l > 0 else "geen data"

        with at1:
            metric_row([
                ("Gem. voedingen/dag", str(gem_voedingen),             f"over {teldagen} thuisdagen" if opvang_uitsluiten else f"over {dagen} dagen"),
                ("Gem. per voeding",   f"{int(gem_ml)} ml" if gem_ml else "–", "borst & fles"),
                ("Gem. slaap/dag",     f"{gem_slaap_u} u" if gem_slaap_u else "–", "totaal per dag"),
                ("Gem. luiers/dag",    str(gem_luiers),                luier_sub),
            ])

            col_links, col_rechts = st.columns(2)

            with col_links:
                if not slaap_df.empty:
                    # Toon alle dagen maar markeer opvangdagen
                    slaap_days = sorted(slaap_df['Datum'].unique())[-min(dagen, 10):]
                    gantt_rows = []
                    for d in slaap_days:
                        for _, s in slaap_df[slaap_df['Datum'] == d].iterrows():
                            start_h = s['Starttijd'].hour + s['Starttijd'].minute / 60
                            end_h   = min(24.0, start_h + s['Duur_min'] / 60)
                            is_opvang_dag = d in opvang_set
                            gantt_rows.append({
                                'Dag':      str(d),
                                'Start':    start_h,
                                'Einde':    end_h,
                                'Label':    f"{s['Starttijd'].strftime('%H:%M')} — {int(s['Duur_min'])} min",
                                'Categorie': 'Opvangdag' if is_opvang_dag else 'Thuisdag',
                            })
                    if gantt_rows:
                        gantt_df     = pd.DataFrame(gantt_rows)
                        dag_volgorde = [str(d) for d in sorted(gantt_df['Dag'].unique())]
                        slaap_chart  = alt.Chart(gantt_df).mark_bar(
                            cornerRadius=3, opacity=0.85
                        ).encode(
                            y=alt.Y('Dag:N', sort=dag_volgorde,
                                    axis=alt.Axis(labelFontSize=10, title='', labelLimit=80)),
                            x=alt.X('Start:Q', scale=alt.Scale(domain=[0, 24]),
                                    axis=alt.Axis(
                                        values=[0, 6, 12, 18, 24],
                                        labelExpr="datum.value == 0 ? '00:00' : datum.value == 6 ? '06:00' : datum.value == 12 ? '12:00' : datum.value == 18 ? '18:00' : '24:00'",
                                        labelFontSize=9, title='')),
                            x2=alt.X2('Einde:Q'),
                            color=alt.Color('Categorie:N',
                                scale=alt.Scale(domain=['Thuisdag', 'Opvangdag'], range=['#9b84c4', '#cccccc']),
                                legend=alt.Legend(title=None, orient='bottom', labelFontSize=10)),
                            tooltip=[alt.Tooltip('Dag:N', title='Datum'),
                                     alt.Tooltip('Label:N', title='Slaap'),
                                     alt.Tooltip('Categorie:N', title='Type dag')]
                        ).properties(
                            height=max(140, len(dag_volgorde) * 28),
                            title=alt.TitleParams('Wanneer slaapt de baby?', fontSize=13, fontWeight=600, anchor='start')
                        ).configure_view(strokeWidth=0).configure_axis(grid=False)
                        st.altair_chart(slaap_chart, use_container_width=True)
                else:
                    st.info("Geen slaapdata.")

            with col_rechts:
                if not voeding_fles_borst.empty:
                    hm_rows = []
                    for h_start in range(0, 24, 2):
                        for d in sorted(voeding_fles_borst['Datum'].unique()):
                            day_df = voeding_fles_borst[voeding_fles_borst['Datum'] == d]
                            cnt = int(((day_df['Starttijd'].dt.hour == h_start) |
                                       (day_df['Starttijd'].dt.hour == h_start + 1)).sum())
                            # Markeer opvangdagen met negatieve waarde als signaal
                            is_opvang_dag = d in opvang_set
                            hm_rows.append({'Dag': str(d), 'Uur': f"{h_start:02d}:00", 'Aantal': cnt, 'Type': 'Opvangdag' if is_opvang_dag else 'Thuisdag'})
                    hm_df = pd.DataFrame(hm_rows)
                    heatmap_chart = alt.Chart(hm_df).mark_rect(
                        stroke='white', strokeWidth=1.5
                    ).encode(
                        x=alt.X('Dag:O', sort=sorted(hm_df['Dag'].unique()),
                                axis=alt.Axis(labelAngle=-45, labelFontSize=10, title='', labelOverlap='greedy')),
                        y=alt.Y('Uur:O', sort=[f"{h:02d}:00" for h in range(0, 24, 2)],
                                axis=alt.Axis(labelFontSize=10, title='')),
                        color=alt.condition(
                            alt.datum.Type == 'Opvangdag',
                            alt.value('#f0f0f0'),
                            alt.Color('Aantal:Q',
                                scale=alt.Scale(domain=[0, 1, 2, 3],
                                                range=['#f0f4ef', '#b8d4b0', '#7a9e72', '#4d6b47']),
                                legend=alt.Legend(title='Voedingen', orient='right',
                                                  labelFontSize=10, titleFontSize=10, gradientLength=80))
                        ),
                        tooltip=[alt.Tooltip('Dag:O', title='Datum'),
                                 alt.Tooltip('Uur:O', title='Tijd'),
                                 alt.Tooltip('Aantal:Q', title='Voedingen'),
                                 alt.Tooltip('Type:N', title='Type dag')]
                    ).properties(
                        height=300,
                        title=alt.TitleParams('Wanneer wordt er gevoed?', fontSize=13, fontWeight=600, anchor='start')
                    ).configure_view(strokeWidth=0)
                    st.altair_chart(heatmap_chart, use_container_width=True)
                else:
                    st.info("Geen voedingsdata.")

            # Luiers per dag — opvangdagen gestreept
            if not luier_df.empty:
                luier_dag = luier_df.groupby(['Datum', 'Type Luier']).size().reset_index(name='Aantal')
                luier_dag['Datum'] = luier_dag['Datum'].astype(str)
                luier_dag['Opvang'] = luier_dag['Datum'].apply(lambda d: d in [str(x) for x in opvang_set])

                base = alt.Chart(luier_dag)
                bars = base.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                    x=alt.X('Datum:O', axis=alt.Axis(labelAngle=-45, labelFontSize=9, title='', labelOverlap='greedy')),
                    y=alt.Y('Aantal:Q', title='', stack='zero', scale=alt.Scale(domain=[0, 12]), axis=alt.Axis(tickCount=6, grid=True, gridColor='#f0f0f0')),
                    color=alt.Color('Type Luier:N',
                                    scale=alt.Scale(domain=['Nat','Vuil'], range=['#6b9ec4','#e8956d']),
                                    legend=alt.Legend(orient='bottom', labelFontSize=11, title=None)),
                    order=alt.Order('Type Luier:N', sort='ascending'),
                    opacity=alt.condition(alt.datum.Opvang, alt.value(0.35), alt.value(1.0)),
                    tooltip=['Datum', 'Type Luier', 'Aantal']
                ).properties(width='container', height=300,
                    title=alt.TitleParams('Luiers per dag', fontSize=13, fontWeight=600, anchor='start')
                ).configure_view(strokeWidth=0).configure_axis(labelFont='sans-serif')
                st.altair_chart(bars, use_container_width=True)
                if opvang_set and opvang_uitsluiten:
                    st.caption("Transparante staven = opvangdagen (niet meegeteld in gemiddelden)")
            else:
                st.info("Geen luierdata.")

        with at2:
            langste_slaap = "–"
            if not slaap_df_gem.empty and slaap_df_gem['Duur_min'].max() > 0:
                lm = int(slaap_df_gem['Duur_min'].max())
                langste_slaap = f"{lm//60}u {lm%60}m"
            gem_interval = "–"
            if len(voeding_fles_borst_gem) > 1:
                tijden    = voeding_fles_borst_gem['Starttijd'].sort_values()
                intervals = tijden.diff().dt.total_seconds().dropna() / 3600
                intervals = intervals[intervals < 12]
                if len(intervals) > 0:
                    gi = intervals.mean()
                    gem_interval = f"{int(gi)}u {int((gi%1)*60)}m"
            laatste_gewicht = "–"
            if not gezond_df.empty:
                gw = pd.to_numeric(gezond_df['Gewicht'], errors='coerce').dropna()
                if len(gw) > 0:
                    laatste_gewicht = f"{gw.iloc[-1]:.2f} kg"

            metric_row([
                ("Totaal voeding",  f"{int(voeding_fles_borst_gem['Hoeveelheid'].sum()) if not voeding_fles_borst_gem.empty else 0} ml", f"in {teldagen} thuisdagen" if opvang_uitsluiten else f"in {dagen} dagen"),
                ("Langste slaap",   langste_slaap,   "aaneengesloten"),
                ("Gem. interval",   gem_interval,    "tussen voedingen"),
                ("Laatste gewicht", laatste_gewicht, "meest recente meting"),
            ])

            if not voeding_fles_borst_gem.empty:
                daily_ml = voeding_fles_borst_gem.groupby('Datum')['Hoeveelheid'].sum().reset_index()
                daily_ml['Datum'] = daily_ml['Datum'].astype(str)
                chart = alt.Chart(daily_ml).mark_bar(
                    color='#7a9e72', opacity=0.85, cornerRadiusTopLeft=4, cornerRadiusTopRight=4
                ).encode(
                    x=alt.X('Datum:O', axis=alt.Axis(labelAngle=-45, labelFontSize=9, title='', labelOverlap='greedy')),
                    y=alt.Y('Hoeveelheid:Q', title='ml', axis=alt.Axis(grid=True, gridColor='#f0f0f0')),
                    tooltip=[alt.Tooltip('Datum:O'), alt.Tooltip('Hoeveelheid:Q', title='ml')]
                ).properties(height=200,
                    title=alt.TitleParams('Totale voeding per dag (ml)', fontSize=13, fontWeight=600, anchor='start')
                ).configure_view(strokeWidth=0).configure_axis(labelFont='sans-serif')
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("Geen voedingsdata.")

            col_s, col_g = st.columns(2)
            with col_s:
                if not slaap_df_gem.empty:
                    daily_slaap = slaap_df_gem.groupby('Datum')['Duur_min'].sum().reset_index()
                    daily_slaap['Uur']   = (daily_slaap['Duur_min'] / 60).round(1)
                    daily_slaap['Datum'] = daily_slaap['Datum'].astype(str)
                    base  = alt.Chart(daily_slaap)
                    area  = base.mark_area(color='#9b84c4', opacity=0.1).encode(x='Datum:O', y='Uur:Q')
                    line  = base.mark_line(color='#9b84c4', strokeWidth=2).encode(
                        x=alt.X('Datum:O', axis=alt.Axis(labelAngle=-45, labelFontSize=9, title='')),
                        y=alt.Y('Uur:Q', title='uur'),
                        tooltip=[alt.Tooltip('Datum:O'), alt.Tooltip('Uur:Q', title='uur')])
                    pts   = base.mark_point(color='#9b84c4', filled=True, size=40).encode(x='Datum:O', y='Uur:Q')
                    chart = (area + line + pts).properties(height=200,
                        title=alt.TitleParams('Slaapduur per dag (uur)', fontSize=13, fontWeight=600, anchor='start')
                    ).configure_view(strokeWidth=0).configure_axis(grid=False, labelFont='sans-serif')
                    st.altair_chart(chart, use_container_width=True)
                else:
                    st.info("Geen slaapdata.")

            with col_g:
                if not gezond_df.empty:
                    gezond_df['Datum']       = gezond_df['Starttijd'].dt.date.astype(str)
                    gezond_df['Gewicht_num'] = pd.to_numeric(gezond_df['Gewicht'], errors='coerce')
                    gw_df = gezond_df.dropna(subset=['Gewicht_num'])
                    if not gw_df.empty:
                        base  = alt.Chart(gw_df)
                        area  = base.mark_area(color='#e8956d', opacity=0.1).encode(x='Datum:O', y='Gewicht_num:Q')
                        line  = base.mark_line(color='#e8956d', strokeWidth=2).encode(
                            x=alt.X('Datum:O', axis=alt.Axis(labelAngle=-45, labelFontSize=9, title='')),
                            y=alt.Y('Gewicht_num:Q', title='kg', scale=alt.Scale(zero=False)),
                            tooltip=[alt.Tooltip('Datum:O'), alt.Tooltip('Gewicht_num:Q', title='kg')])
                        pts   = base.mark_point(color='#e8956d', filled=True, size=40).encode(x='Datum:O', y='Gewicht_num:Q')
                        chart = (area + line + pts).properties(height=200,
                            title=alt.TitleParams('Gewichtsontwikkeling (kg)', fontSize=13, fontWeight=600, anchor='start')
                        ).configure_view(strokeWidth=0).configure_axis(grid=False, labelFont='sans-serif')
                        st.altair_chart(chart, use_container_width=True)
                    else:
                        st.info("Geen gewichtsdata.")
                else:
                    st.info("Geen gezondheidsdata.")

        with at3:
            if act_df_gem.empty:
                st.info("Geen activiteiten geregistreerd in deze periode.")
            else:
                meest           = act_df_gem['Activiteit_type'].value_counts()
                meest_naam      = meest.index[0]   if len(meest) > 0 else "–"
                meest_aantal    = int(meest.iloc[0]) if len(meest) > 0 else 0
                gem_act_per_dag = round(len(act_df_gem) / teldagen, 1) if len(act_df_gem) > 0 else "–"
                reactie_counts  = act_df_gem['Reactie'].value_counts() if 'Reactie' in act_df_gem.columns else pd.Series()
                fav_reactie     = reactie_counts.index[0] if len(reactie_counts) > 0 else "–"
                reactie_icons   = {'Heel blij':'😄','Blij':'😊','Neutraal':'😐','Huilerig':'😢','Boos':'😠'}
                fav_icon        = reactie_icons.get(fav_reactie, '')

                metric_row([
                    ("Meest gedaan",         meest_naam,               f"{meest_aantal}× in {teldagen} dagen"),
                    ("Favoriete reactie",     f"{fav_icon} {fav_reactie}", "meest voorkomende reactie"),
                    ("Gem. activiteiten/dag", str(gem_act_per_dag),    f"over {teldagen} thuisdagen" if opvang_uitsluiten else f"over {dagen} dagen"),
                ])

                if 'Reactie' in act_df_gem.columns and not act_df_gem['Reactie'].isna().all():
                    reactie_df = act_df_gem.groupby(['Activiteit_type', 'Reactie']).size().reset_index(name='Aantal')
                    chart = alt.Chart(reactie_df).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                        x=alt.X('Activiteit_type:N', title='', axis=alt.Axis(labelAngle=-20, labelFontSize=10, labelLimit=120, labelOverlap=False)),
                        y=alt.Y('Aantal:Q', title='', axis=alt.Axis(grid=True, gridColor='#f0f0f0', tickMinStep=1, format='d')),
                        color=alt.Color('Reactie:N',
                                        scale=alt.Scale(domain=['Boos','Huilerig','Neutraal','Blij','Heel blij'],
                                                        range=['#d63031','#e8956d','#b2bec3','#7a9e72','#4d6b47']),
                                        legend=alt.Legend(orient='bottom', labelFontSize=10, title=None, columns=5, symbolSize=80)),
                        order=alt.Order('Reactie:N', sort='ascending'),
                        tooltip=['Activiteit_type', 'Reactie', 'Aantal']
                    ).properties(height=280,
                        title=alt.TitleParams('Reactie per activiteit', fontSize=13, fontWeight=600, anchor='start')
                    ).configure_view(strokeWidth=0).configure_axis(labelFont='sans-serif')
                    st.altair_chart(chart, use_container_width=True)

                if 'Duur' in act_df_gem.columns:
                    duur_df = act_df_gem.copy()
                    duur_df['Duur_num'] = pd.to_numeric(duur_df['Duur'], errors='coerce')
                    duur_gem = duur_df.groupby('Activiteit_type')['Duur_num'].mean().reset_index()
                    duur_gem.columns = ['Activiteit', 'Gem_duur']
                    duur_gem = duur_gem.dropna().sort_values('Gem_duur', ascending=False).head(8)
                    if not duur_gem.empty:
                        duur_chart = alt.Chart(duur_gem).mark_bar(
                            color='#9b84c4', opacity=0.85, cornerRadiusTopRight=4, cornerRadiusBottomRight=4
                        ).encode(
                            x=alt.X('Gem_duur:Q', title='minuten', axis=alt.Axis(grid=True, gridColor='#f0f0f0')),
                            y=alt.Y('Activiteit:N', sort='-x', title='', axis=alt.Axis(labelFontSize=12, labelLimit=200)),
                            tooltip=[alt.Tooltip('Activiteit:N'), alt.Tooltip('Gem_duur:Q', title='gem. minuten', format='.0f')]
                        ).properties(height=max(200, len(duur_gem) * 45),
                            title=alt.TitleParams('Gemiddelde duur per activiteit (min)', fontSize=13, fontWeight=600, anchor='start')
                        ).configure_view(strokeWidth=0).configure_axis(labelFont='sans-serif')
                        st.altair_chart(duur_chart, use_container_width=True)

                if 'Opmerking' in act_df_gem.columns:
                    opm_df = act_df_gem[act_df_gem['Opmerking'].notna() & (act_df_gem['Opmerking'] != '')][
                        ['Starttijd','Activiteit_type','Reactie','Opmerking']
                    ].sort_values('Starttijd', ascending=False)
                    if not opm_df.empty:
                        with st.expander(f"📝 Opmerkingen ({len(opm_df)})"):
                            activiteit_opties = sorted(opm_df['Activiteit_type'].dropna().unique().tolist())
                            filter_keuze = st.selectbox("Filter", ["Alle"] + activiteit_opties, key="opm_filter", label_visibility="collapsed")
                            gefilterd = opm_df if filter_keuze == "Alle" else opm_df[opm_df['Activiteit_type'] == filter_keuze]
                            for _, row in gefilterd.iterrows():
                                datum_opm = row['Starttijd'].strftime('%-d %b %H:%M')
                                st.markdown(f"""
<div style="padding:10px 14px;border-left:3px solid #7a9e72;background:rgba(122,158,114,0.08);border-radius:0 8px 8px 0;margin-bottom:8px;">
  <div style="font-size:11px;color:#888;margin-bottom:2px;">{datum_opm} · {row.get('Activiteit_type','')} · {row.get('Reactie','')}</div>
  <div style="font-size:13px;">{row['Opmerking']}</div>
</div>""", unsafe_allow_html=True)


# ------------------------------
# TAB: Data (ongewijzigd)
# ------------------------------
if selected_tab == "Data":
    st.title("Overzicht records")
    st.caption("Overzicht van ruwe data over een zelf geselecteerde periode.")
    col_d1, col_d2 = st.columns([3, 2])
    with col_d1:
        datum_input = st.date_input("Selecteer periode", [datetime.now() - timedelta(days=7), datetime.now()])
    with col_d2:
        type_filter = st.multiselect("Type", ["Slaap", "Voeding", "Luier", "Gezondheid"],
            default=["Slaap", "Voeding", "Luier", "Gezondheid"], label_visibility="collapsed")
    if isinstance(datum_input, (list, tuple)):
        start_date, end_date = datum_input
    else:
        start_date = end_date = datum_input
    df_period = baby_records[
        (baby_records['Starttijd'].dt.date >= start_date) &
        (baby_records['Starttijd'].dt.date <= end_date)
    ]
    if type_filter:
        df_period = df_period[df_period['Type'].isin(type_filter)]
    if df_period.empty:
        st.info("Geen records beschikbaar")
    else:
        st.dataframe(df_period, use_container_width=True)
        csv = df_period.to_csv(index=False).encode('utf-8')
        st.download_button("Download CSV", csv, "records.csv", "text/csv")

# ------------------------------
# TAB: Instellingen
# GEWIJZIGD: nieuw subtab "Opvangdagen"
# ------------------------------
if selected_tab == "Instellingen":
    st.title("Instellingen")

    if inst.get('opvangdagen_aan', 'nee') == 'ja':
        tab_alg, tab_opvang, tab_voorraad_inst, tab_account = st.tabs([
            "Standaarden", "Opvangdagen", "Voorraad & snelkeuzes", "Account"
        ])
    else:
        tab_opvang = None
        tab_alg, tab_voorraad_inst, tab_account = st.tabs([
            "Standaarden", "Voorraad & snelkeuzes", "Account"
        ])

    with tab_alg:
        st.subheader("Baby")
        baby_naam = st.text_input("Naam baby", value=inst.get('baby_naam', 'Bubbel'))
        geboortedatum_str = inst.get('geboortedatum', '')
        geboortedatum_val = datetime.now(TZ).date()
        if geboortedatum_str:
            try:
                geboortedatum_val = date.fromisoformat(geboortedatum_str)
            except Exception:
                pass
        geboortedatum = st.date_input("Geboortedatum", value=geboortedatum_val, key="inst_geboortedatum")

        opvangdagen_aan = st.toggle(
            "Opvang- of oppassdagen bijhouden",
            value=inst.get('opvangdagen_aan', 'nee') == 'ja',
            help="Schakel in als je kind naar de opvang of oppas gaat. Je kunt dan dagen markeren die niet meetellen in gemiddelden."
        )

        st.divider()

        st.subheader("Voeding")
        voeding_stijl_labels = {'borst': 'Alleen borstvoeding', 'fles': 'Alleen flesvoeding', 'beiden': 'Borst én fles'}
        voeding_stijl_labels_inv = {v: k for k, v in voeding_stijl_labels.items()}
        huidig_stijl = inst.get('voeding_stijl', 'fles')
        huidig_label = voeding_stijl_labels.get(huidig_stijl, 'Alleen flesvoeding')
        voeding_stijl_keuze = st.segmented_control("Voedingsvorm", list(voeding_stijl_labels.values()), default=huidig_label, label_visibility="collapsed")
        voeding_stijl = voeding_stijl_labels_inv.get(voeding_stijl_keuze, huidig_stijl)
        col_h, col_k = st.columns(2)
        with col_h:
            hapjes_aan = st.toggle("Hapjes bijhouden", value=inst.get('hapjes_aan', 'nee') == 'ja')
        with col_k:
            kolven_aan = st.toggle("Kolven bijhouden", value=inst.get('kolven_aan', 'nee') == 'ja')

        if voeding_stijl in ('fles', 'beiden'):
            st.markdown("**Flesvoeding**")
            col1, col2 = st.columns(2)
            with col1:
                fles_types = ['melk', 'kunstvoeding']
                voeding_default_flestype = st.selectbox("Standaard flestype", fles_types, index=fles_types.index(inst.get('voeding_default_flestype', 'kunstvoeding')))
                voeding_default_ml = st.number_input("Standaard hoeveelheid (ml)", min_value=0, value=int(inst.get('voeding_default_ml', 100)))
            with col2:
                kunstvoeding_gram_per_schep = st.number_input("Gram poeder per schep", min_value=0.1, step=0.1, value=float(inst.get('kunstvoeding_gram_per_schep', 4.4)))
                kv_huidig = inst.get('kunstvoeding_productnaam', '')
                if not voorraad.empty:
                    prod_namen = voorraad['Productnaam'].tolist()
                    kv_opties = ["— Geen koppeling —"] + prod_namen
                    kv_idx = prod_namen.index(kv_huidig) + 1 if kv_huidig in prod_namen else 0
                    kv_keuze = st.selectbox("Koppel aan voorraadproduct", kv_opties, index=kv_idx)
                    kunstvoeding_productnaam = '' if kv_keuze == "— Geen koppeling —" else kv_keuze
                else:
                    kunstvoeding_productnaam = kv_huidig
        else:
            voeding_default_flestype = inst.get('voeding_default_flestype', 'kunstvoeding')
            voeding_default_ml = int(inst.get('voeding_default_ml', 100))
            kunstvoeding_gram_per_schep = float(inst.get('kunstvoeding_gram_per_schep', 4.4))
            kunstvoeding_productnaam = inst.get('kunstvoeding_productnaam', 'Kunstvoeding')

        voeding_default_hapje_gram = int(inst.get('voeding_default_hapje_gram', 50))
        if hapjes_aan:
            voeding_default_hapje_gram = st.number_input("Standaard hoeveelheid hapje (gram)", min_value=0, value=voeding_default_hapje_gram)
        voeding_default_kolven_ml = int(inst.get('voeding_default_kolven_ml', 10))
        if voeding_stijl in ('borst', 'beiden') or kolven_aan:
            voeding_default_kolven_ml = st.number_input("Standaard hoeveelheid kolven (ml)", min_value=0, value=voeding_default_kolven_ml)

        st.divider()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("**Slaap**")
            slaap_default_duur = st.number_input("Standaard duur (min)", min_value=0, value=int(inst.get('slaap_default_duur', 60)))
        with col2:
            st.markdown("**Luiers**")
            luier_default_type = st.segmented_control("Standaard type", ['Nat', 'Vuil'],
                default=inst.get('luier_default_type', 'Nat') if inst.get('luier_default_type', 'Nat') in ['Nat', 'Vuil'] else 'Nat')
        with col3:
            st.markdown("**Activiteiten**")
            activiteit_default_duur = st.number_input("Standaard duur (min)", min_value=0, value=int(inst.get('activiteit_default_duur', 15)), key="act_def_duur")

        st.divider()
        st.markdown("**Gezondheid — standaard invulwaarden**")
        col1, col2, col3 = st.columns(3)
        with col1:
            gezondheid_default_gewicht = st.number_input("Gewicht (kg)", min_value=0.0, step=0.1, value=float(inst.get('gezondheid_default_gewicht', 5.0)))
        with col2:
            gezondheid_default_lengte = st.number_input("Lengte (cm)", min_value=0.0, step=0.1, value=float(inst.get('gezondheid_default_lengte', 50.0)))
        with col3:
            gezondheid_default_temp = st.number_input("Temperatuur (°C)", min_value=0.0, max_value=45.0, step=0.1, value=float(inst.get('gezondheid_default_temp', 36.5)))

        st.divider()
        st.markdown("**Eigen activiteiten**")
        eigen_raw = inst.get('eigen_activiteiten', '')
        eigen_lijst = parse_eigen_activiteiten(eigen_raw)

        for i, item in enumerate(eigen_lijst):
            ec1, ec2, ec3, ec4 = st.columns([1, 4, 1, 1])
            with ec1:
                nieuw_icon = st.text_input("Icon", value=item["icon"], key=f'edit_act_icon_{i}',
                                           label_visibility='collapsed', max_chars=2)
            with ec2:
                nieuwe_naam = st.text_input("Naam", value=item["naam"], key=f'edit_act_{i}',
                                            label_visibility='collapsed')
            with ec3:
                if st.button("Opslaan", key=f'save_act_{i}', use_container_width=True):
                    andere_namen = [e["naam"] for j, e in enumerate(eigen_lijst) if j != i]
                    if not nieuwe_naam:
                        st.warning("Vul een naam in")
                    elif nieuwe_naam in andere_namen:
                        st.warning("Naam bestaat al")
                    else:
                        eigen_lijst[i] = {"naam": nieuwe_naam, "icon": nieuw_icon or "🎈"}
                        save_instelling('eigen_activiteiten', json.dumps(eigen_lijst))
                        st.cache_data.clear()
                        st.rerun()
            with ec4:
                if st.button("Verwijder", key=f'del_act_{i}', use_container_width=True):
                    eigen_lijst.pop(i)
                    save_instelling('eigen_activiteiten', json.dumps(eigen_lijst))
                    st.cache_data.clear()
                    st.rerun()

        ea1, ea2, ea3 = st.columns([1, 4, 1])
        with ea1:
            nieuw_icon_add = st.text_input("Icon", key="nieuwe_act_icon", label_visibility='collapsed',
                                           placeholder="🎈", max_chars=2)
        with ea2:
            nieuwe_activiteit = st.text_input("Naam nieuwe activiteit", key="nieuwe_act",
                                              label_visibility='collapsed',
                                              placeholder="bijv. Zwembad, Opa & oma, Fysiotherapie")
        with ea3:
            if st.button("Toevoegen", key="add_act"):
                bestaande_namen = [e["naam"] for e in eigen_lijst]
                if not nieuwe_activiteit:
                    st.warning("Vul een naam in")
                elif nieuwe_activiteit in bestaande_namen:
                    st.warning("Naam bestaat al")
                else:
                    eigen_lijst.append({"naam": nieuwe_activiteit, "icon": nieuw_icon_add or "🎈"})
                    save_instelling('eigen_activiteiten', json.dumps(eigen_lijst))
                    st.cache_data.clear()
                    st.rerun()

        st.divider()
        if st.button("Opslaan", key="inst_opslaan", use_container_width=True, type="primary"):
            for sleutel, waarde in {
                'baby_naam': baby_naam,
                'geboortedatum': geboortedatum.isoformat() if geboortedatum else '',
                'voeding_stijl': voeding_stijl,
                'hapjes_aan': 'ja' if hapjes_aan else 'nee',
                'kolven_aan': 'ja' if kolven_aan else 'nee',
                'voeding_default_flestype': voeding_default_flestype,
                'voeding_default_ml': voeding_default_ml,
                'voeding_default_kolven_ml': voeding_default_kolven_ml,
                'voeding_default_hapje_gram': voeding_default_hapje_gram,
                'kunstvoeding_gram_per_schep': kunstvoeding_gram_per_schep,
                'kunstvoeding_productnaam': kunstvoeding_productnaam,
                'slaap_default_duur': slaap_default_duur,
                'luier_default_type': luier_default_type,
                'activiteit_default_duur': activiteit_default_duur,
                'gezondheid_default_gewicht': gezondheid_default_gewicht,
                'gezondheid_default_lengte': gezondheid_default_lengte,
                'gezondheid_default_temp': gezondheid_default_temp,
                'opvangdagen_aan': 'ja' if opvangdagen_aan else 'nee',
            }.items():
                save_instelling(sleutel, waarde)
            st.cache_data.clear()
            st.success("Instellingen opgeslagen ✅")
            st.rerun()

    # ── Tab Opvangdagen ────────────────────────────────────────────────────
    if tab_opvang is not None:
        with tab_opvang:
            WEEKDAGEN = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]

            st.subheader("Vaste opvangdagen")
            st.caption("Selecteer de weekdagen waarop je kind naar de opvang of oppas gaat. Deze dagen worden automatisch als opvangdag herkend.")

            startdatum_str = inst.get('opvang_startdatum', '')
            startdatum_val = date.today()
            if startdatum_str:
                try:
                    startdatum_val = date.fromisoformat(startdatum_str)
                except Exception:
                    pass
            opvang_startdatum = st.date_input(
                "Startdatum opvang",
                value=startdatum_val,
                key="opvang_startdatum_input",
                help="Vaste opvangdagen gelden pas vanaf deze datum. Dagen daarvoor worden nooit als opvangdag gemarkeerd."
            )

            try:
                vaste_dagen_idx = json.loads(inst.get('vaste_opvangdagen', '[]'))
            except Exception:
                vaste_dagen_idx = []

            nieuwe_vaste_dagen = []
            cols_wd = st.columns(7)
            for i, dag_naam in enumerate(WEEKDAGEN):
                with cols_wd[i]:
                    st.caption(dag_naam[:2])
                    if st.toggle("", value=i in vaste_dagen_idx, key=f"vaste_opvang_{i}", label_visibility="collapsed"):
                        nieuwe_vaste_dagen.append(i)

            if st.button("Opslaan", use_container_width=True, type="primary", key="vaste_opvang_opslaan"):
                save_instelling('vaste_opvangdagen', json.dumps(nieuwe_vaste_dagen))
                save_instelling('opvang_startdatum', opvang_startdatum.isoformat())
                st.cache_data.clear()
                st.success("Vaste opvangdagen opgeslagen ✅")
                st.rerun()

            st.divider()
            st.subheader("Uitzonderingen")
            st.caption("Hier zie je handmatige aanpassingen: extra opvangdagen (buiten het vaste patroon) en overgeslagen vaste dagen. Je kunt een uitzondering verwijderen om terug te keren naar het vaste patroon.")

            uitz = get_uitzonderingen()
            if not uitz:
                st.info("Geen uitzonderingen.")
            else:
                vandaag_inst = datetime.now(TZ).date()
                gesorteerd = sorted(uitz.items(), key=lambda x: x[0])
                recent = [(d, t) for d, t in gesorteerd if d >= vandaag_inst - timedelta(days=30)]
                if not recent:
                    st.info("Geen recente uitzonderingen.")
                else:
                    for d, t in recent:
                        dag_naam_kort = WEEKDAGEN[d.weekday()]
                        verleden = d < vandaag_inst
                        label = f"{dag_naam_kort} {d.strftime('%-d %b %Y')}"
                        type_label = "➕ Extra dag" if t == 'extra' else "⏭️ Overgeslagen"
                        type_kleur = "#7a9e72" if t == 'extra' else "#aaa"
                        stijl_label = "color:#aaa;" if verleden else ""
                        c1, c2, c3 = st.columns([3, 2, 1])
                        with c1:
                            st.markdown(f'<div style="font-size:13px;{stijl_label}padding-top:6px;">{label}</div>', unsafe_allow_html=True)
                        with c2:
                            st.markdown(f'<div style="font-size:12px;color:{type_kleur};padding-top:7px;">{type_label}</div>', unsafe_allow_html=True)
                        with c3:
                            if st.button("✕", key=f"del_uitz_{d.isoformat()}", use_container_width=True, help="Uitzondering verwijderen"):
                                try:
                                    supabase.table("opvangdagen").delete().eq("user_id", user_id).eq("datum", d.isoformat()).execute()
                                    st.cache_data.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Fout: {e}")

    with tab_voorraad_inst:
        st.subheader("Producten")
        if voorraad.empty:
            st.info("Nog geen producten. Voeg ze toe via de Voorraad tab.")
        else:
            handmatig_raw_inst = inst.get('handmatige_producten', '[]')
            try:
                handmatig_lijst_inst = json.loads(handmatig_raw_inst)
            except Exception:
                handmatig_lijst_inst = []
            for _, r in voorraad.iterrows():
                prod_id = r.get('id')
                prod_naam = r.get('Productnaam', '')
                prod_eenheid = r.get('Eenheid', 'stuks')
                prod_variant = r.get('Variant', '') or ''
                prod_min = float(pd.to_numeric(r.get('Minimum voorraad', 0), errors='coerce') or 0)
                prod_is_handmatig = prod_naam in handmatig_lijst_inst
                pc1, pc2, pc3, pc4, pc5, pc6 = st.columns([2, 2, 1, 1, 1, 1])
                with pc1:
                    st.text(prod_naam)
                with pc2:
                    nieuw_variant = st.text_input('Variant', value=prod_variant, key=f'inst_variant_{prod_id}', label_visibility='collapsed', placeholder='bijv. Maat 2')
                with pc3:
                    nieuw_min = st.number_input('Min.', min_value=0.0, step=1.0, value=prod_min, key=f'inst_min_{prod_id}', label_visibility='collapsed')
                with pc4:
                    nieuw_handmatig_inst = st.toggle('Handmatig', value=prod_is_handmatig, key=f'inst_handmatig_{prod_id}', label_visibility='collapsed')
                with pc5:
                    st.caption(prod_eenheid)
                with pc6:
                    if st.button("Sla op", key=f'inst_save_{prod_id}'):
                        try:
                            supabase.table("voorraad").update({"minimum_voorraad": nieuw_min, "variant": nieuw_variant}).eq("id", str(prod_id)).eq("user_id", user_id).execute()
                            if nieuw_handmatig_inst and prod_naam not in handmatig_lijst_inst:
                                handmatig_lijst_inst.append(prod_naam)
                            elif not nieuw_handmatig_inst and prod_naam in handmatig_lijst_inst:
                                handmatig_lijst_inst.remove(prod_naam)
                            save_instelling('handmatige_producten', json.dumps(handmatig_lijst_inst))
                            st.toast(f"Wijzigingen {prod_naam} opgeslagen ✅")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fout: {e}")

        st.divider()
        st.subheader("Snelkeuzes bijvullen")
        if voorraad.empty:
            st.info("Geen voorraadproducten gevonden.")
        else:
            for _, r in voorraad.iterrows():
                prod_naam = r.get('Productnaam', '')
                prod_eenheid = r.get('Eenheid', 'stuks')
                sleutel = f'snelkeuze_{prod_naam}'
                huidig_raw = inst.get(sleutel, '')
                try:
                    huidig = json.loads(huidig_raw) if huidig_raw else []
                except Exception:
                    huidig = []
                with st.expander(f"{prod_naam} — {len(huidig)} snelkeuze(s)"):
                    for idx_sk, optie in enumerate(huidig):
                        sk1, sk2, sk3 = st.columns([3, 2, 1])
                        with sk1:
                            nieuw_label = st.text_input('Label', value=optie.get('label', ''), key=f'sk_label_{prod_naam}_{idx_sk}', label_visibility='collapsed', placeholder='bijv. Midi pak (48)')
                        with sk2:
                            nieuw_waarde = st.number_input(f'Waarde ({prod_eenheid})', min_value=0.0, step=1.0, value=float(optie.get('waarde', 0)), key=f'sk_waarde_{prod_naam}_{idx_sk}', label_visibility='collapsed')
                        with sk3:
                            if st.button("Verwijder", key=f'sk_del_{prod_naam}_{idx_sk}'):
                                huidig.pop(idx_sk)
                                save_instelling(sleutel, json.dumps(huidig))
                                st.cache_data.clear()
                                st.rerun()
                        if idx_sk < len(huidig):
                            huidig[idx_sk] = {'label': nieuw_label, 'waarde': nieuw_waarde}
                    st.markdown("**Nieuwe optie**")
                    na1, na2, na3 = st.columns([3, 2, 1])
                    with na1:
                        nieuw_label_add = st.text_input('Label', key=f'sk_new_label_{prod_naam}', label_visibility='collapsed', placeholder='bijv. 1 pak')
                    with na2:
                        nieuw_waarde_add = st.number_input(f'Waarde ({prod_eenheid})', min_value=0.0, step=1.0, key=f'sk_new_waarde_{prod_naam}', label_visibility='collapsed')
                    with na3:
                        if st.button("Voeg toe", key=f'sk_add_{prod_naam}'):
                            if nieuw_label_add:
                                huidig.append({'label': nieuw_label_add, 'waarde': nieuw_waarde_add})
                                save_instelling(sleutel, json.dumps(huidig))
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.warning("Vul een label in")
                    if huidig:
                        if st.button(f"Opslaan", key=f'sk_save_{prod_naam}', use_container_width=True):
                            save_instelling(sleutel, json.dumps(huidig))
                            st.cache_data.clear()
                            st.success("Snelkeuzes opgeslagen ✅")
                            st.rerun()

    with tab_account:
        user_email = st.session_state["session"]["user"].email
        st.subheader("Account")
        st.caption(f"Ingelogd als **{user_email}**")
        st.divider()
        st.markdown("**E-mailadres wijzigen**")
        nieuw_email = st.text_input("Nieuw e-mailadres", key="nieuw_email")
        if st.button("Opslaan", key="save_email"):
            if nieuw_email:
                try:
                    supabase.auth.update_user({"email": nieuw_email})
                    st.success("Bevestigingsmail verstuurd.")
                except Exception as e:
                    st.error(f"Mislukt: {e}")
            else:
                st.warning("Vul een nieuw e-mailadres in")
        st.divider()
        st.markdown("**Wachtwoord wijzigen**")
        nieuw_ww = st.text_input("Nieuw wachtwoord", type="password", key="nieuw_ww")
        nieuw_ww2 = st.text_input("Wachtwoord herhalen", type="password", key="nieuw_ww2")
        if st.button("Opslaan", key="save_ww"):
            if not nieuw_ww:
                st.warning("Vul een nieuw wachtwoord in")
            elif nieuw_ww != nieuw_ww2:
                st.error("Wachtwoorden komen niet overeen")
            elif len(nieuw_ww) < 6:
                st.error("Wachtwoord moet minimaal 6 tekens zijn")
            else:
                try:
                    supabase.auth.update_user({"password": nieuw_ww})
                    st.success("Wachtwoord gewijzigd ✅")
                except Exception as e:
                    st.error(f"Mislukt: {e}")

# ------------------------------
# TAB: Info (ongewijzigd)
# ------------------------------
if selected_tab == "Info":
    st.markdown("""
<div style="margin-bottom:32px;">
  <div style="font-size:36px;font-weight:800;letter-spacing:-1px;line-height:1.1;">Bubbel<span style="color:#7a9e72;">.</span></div>
  <div style="font-size:15px;color:#aaa;margin-top:6px;">Een persoonlijke babytracker — zonder advertenties, zonder gedoe.</div>
</div>
""", unsafe_allow_html=True)
    st.markdown("""
<div style="background:rgba(122,158,114,0.08);border-left:3px solid #7a9e72;border-radius:0 12px 12px 0;padding:16px 20px;margin-bottom:32px;">
  <div style="font-size:13px;line-height:1.7;color:inherit;">
    Bubbel. ontstond uit een concrete behoefte: de eerste weken van mijn kind bijhouden zonder afhankelijk te zijn van een commerciële app.
    Bestaande oplossingen vroegen om een account bij een bedrijf dat onduidelijk maakte wat er met de ingevoerde gegevens gebeurde.
    Dat voelde niet goed. Uit die behoefte is dit hobbyproject ontstaan met als doel eenvoud, overzicht en volledige controle over je eigen data. En de naam? Zo noemden wij ons kindje tijdens de zwangerschap ;).
  </div>
</div>
""", unsafe_allow_html=True)

    features = [
        ("💤", "Slaap", "Starttijd, duur of eindtijd. Slaapjes over middernacht worden correct meegenomen in het dagoverzicht."),
        ("🍼", "Voeding", "Borst, fles, kolven en hapjes. Bij kunstvoeding wordt de voorraad automatisch bijgewerkt."),
        ("🧷", "Luiers", "Nat en vuil per tijdstip. Voorraad luiers wordt automatisch verlaagd bij elke registratie."),
        ("🩺", "Gezondheid", "Gewicht, lengte en temperatuur over tijd. De laatste meting is zichtbaar op het dashboard."),
        ("🎈", "Activiteiten", "Bijhouden wat jullie doen en hoe de baby reageert. Eigen activiteiten toe te voegen via instellingen."),
        ("🛒", "Voorraad", "Producten met minimum en verbruiksschatting. Melding op dashboard als voorraad laag is."),
        ("🏠", "Opvang- en oppasdagen", "Optioneel: markeer vaste opvangdagen per weekdag met een startdatum. Dagen kunnen eenmalig worden overgeslagen of toegevoegd via het dashboard. Opvangdagen tellen niet mee in gemiddelden."),
    ]
    col1, col2 = st.columns(2)
    for i, (icon, titel, beschrijving) in enumerate(features):
        col = col1 if i % 2 == 0 else col2
        with col:
            st.markdown(f"""
<div style="border:1px solid rgba(128,128,128,0.15);border-radius:12px;padding:16px;margin-bottom:12px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
    <span style="font-size:18px;">{icon}</span>
    <span style="font-weight:700;font-size:14px;">{titel}</span>
  </div>
  <div style="font-size:12px;color:#888;line-height:1.6;">{beschrijving}</div>
</div>
""", unsafe_allow_html=True)

    privacy_items = [
        ("🔒", "Jouw data, alleen van jou", "Elke gebruiker heeft een eigen afgeschermd gedeelte in de database via Row Level Security."),
        ("🚫", "Geen advertenties of tracking", "Er worden geen gegevens gedeeld met derden. Geen advertenties, geen analytische tracking."),
        ("📤", "Data exporteren", "Via de Data tab zijn alle gegevens te downloaden als CSV bestand."),
        ("🗑️", "Account verwijderen", "Wil je je account laten verwijderen? Neem contact op via het e-mailadres waarmee je geregistreerd hebt."),
    ]
    for icon, titel, tekst in privacy_items:
        st.markdown(f"""
<div style="display:flex;gap:14px;align-items:flex-start;padding:14px 0;border-bottom:1px solid rgba(128,128,128,0.1);">
  <div style="font-size:20px;margin-top:1px;flex-shrink:0;">{icon}</div>
  <div>
    <div style="font-weight:600;font-size:13px;margin-bottom:3px;">{titel}</div>
    <div style="font-size:12px;color:#888;line-height:1.6;">{tekst}</div>
  </div>
</div>
""", unsafe_allow_html=True)
    st.markdown("""
<div style="margin-top:32px;padding-top:20px;text-align:center;">
  <div style="font-size:22px;font-weight:800;letter-spacing:-0.5px;">Bubbel<span style="color:#7a9e72;">.</span></div>
  <div style="font-size:11px;color:#bbb;margin-top:4px;">Versie 2.1 · Een hobbyproject · Gemaakt met ♥</div>
</div>
""", unsafe_allow_html=True)