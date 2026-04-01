import streamlit as st
import json
import os
import re
from supabase import create_client, Client
from googleapiclient.discovery import build
from google.oauth2 import service_account
from rapidfuzz import fuzz

# ── Sivun asetukset ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Keikka Manager",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Google-kirjautuminen ──────────────────────────────────────────────────────
@st.cache_resource
def get_google_credentials():
    creds_dict = dict(st.secrets["gcp_service_account"])
    return service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )

@st.cache_resource
def get_drive_service():
    return build("drive", "v3", credentials=get_google_credentials())

# ── Supabase-yhteys ───────────────────────────────────────────────────────────
@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

# ── Google Drive: listaa PDF:t ────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def list_drive_pdfs(folder_id: str) -> list:
    service = get_drive_service()
    query = (
        f"'{folder_id}' in parents "
        "and mimeType='application/pdf' "
        "and trashed=false"
    )
    files = []
    page_token = None
    while True:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, webViewLink, webContentLink)",
            pageToken=page_token,
            pageSize=200,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files

# ── Supabase: hae kappaleet ───────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def get_songs() -> list:
    sb = get_supabase()
    result = sb.table("songs").select("*").order("title").execute()
    return result.data if result.data else []

def save_pdf_to_song(song_id: str, pdf_url: str, pdf_filename: str):
    sb = get_supabase()
    sb.table("songs").update(
        {"pdf_url": pdf_url, "pdf_filename": pdf_filename}
    ).eq("id", song_id).execute()

def remove_pdf_from_song(song_id: str):
    sb = get_supabase()
    sb.table("songs").update(
        {"pdf_url": None, "pdf_filename": None}
    ).eq("id", song_id).execute()

# ── Fuzzy-matchaus ────────────────────────────────────────────────────────────
def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def find_best_pdf_match(song: dict, pdf_files: list) -> dict | None:
    if not pdf_files:
        return None
    title = song.get("title", "")
    artist = song.get("artist", "")
    query = normalize(f"{title} {artist}")
    title_norm = normalize(title)

    best = None
    best_score = 0

    for pdf in pdf_files:
        name_clean = normalize(pdf["name"].replace(".pdf", "").replace("_", " "))
        s1 = fuzz.token_sort_ratio(title_norm, name_clean)
        s2 = fuzz.token_sort_ratio(query, name_clean)
        s3 = fuzz.partial_ratio(title_norm, name_clean)
        score = max(s1, s2, s3)
        if score > best_score:
            best_score = score
            best = {**pdf, "score": score}

    return best if best_score >= 40 else None

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🎵 Keikka Manager")
st.caption("Yhdistä kappaleet nuotteihin Google Drivessa")

# Ladataan data
with st.spinner("Ladataan tietoja..."):
    try:
        DRIVE_FOLDER_ID = st.secrets["drive"]["folder_id"]
    except KeyError:
        st.error("❌ Puuttuva secrets-avain: `drive.folder_id`")
        st.stop()

    try:
        pdf_files = list_drive_pdfs(folder_id=DRIVE_FOLDER_ID)
    except Exception as e:
        st.error(f"❌ Google Drive -virhe: {e}")
        st.stop()

    try:
        songs = get_songs()
    except Exception as e:
        st.error(f"❌ Supabase-virhe: {e}")
        st.stop()

if not pdf_files:
    st.warning("⚠️ Drivesta ei löytynyt yhtään PDF-tiedostoa. Tarkista kansion ID ja käyttöoikeudet.")
    st.stop()

if not songs:
    st.warning("⚠️ Kappalelistaa ei löytynyt tai se on tyhjä.")
    st.stop()

# Inforivit
col_info1, col_info2 = st.columns(2)
with col_info1:
    st.caption(f"📁 {len(pdf_files)} PDF:ää Drivessa")
with col_info2:
    st.caption(f"🎵 {len(songs)} kappaletta tietokannassa")

st.divider()

# Hakusuodattimet
col_search, col_filter, col_min_score = st.columns([3, 2, 2])
with col_search:
    search = st.text_input("🔍 Hae", placeholder="Kappale tai artisti...")
with col_filter:
    show_only = st.selectbox(
        "Näytä",
        ["Kaikki", "Ilman PDF:ää", "PDF tallennettu"],
    )
with col_min_score:
    min_score = st.slider("Min. osuma-%", 0, 100, 40)

# Suodatus
filtered = songs
if search:
    q = search.lower()
    filtered = [
        s for s in filtered
        if q in s.get("title", "").lower() or q in s.get("artist", "").lower()
    ]
if show_only == "Ilman PDF:ää":
    filtered = [s for s in filtered if not s.get("pdf_url")]
elif show_only == "PDF tallennettu":
    filtered = [s for s in filtered if s.get("pdf_url")]

st.caption(f"Näytetään **{len(filtered)}** / {len(songs)} kappaletta")
st.divider()

# Sarakeotsikit
h1, h2, h3, h4 = st.columns([1, 3, 4, 2])
with h1:
    st.markdown("**#**")
with h2:
    st.markdown("**Kappale**")
with h3:
    st.markdown("**Paras PDF-osuma**")
with h4:
    st.markdown("**Toiminto**")
st.divider()

# ── Kappalelista ──────────────────────────────────────────────────────────────
for i, song in enumerate(filtered, start=1):
    title   = song.get("title", "–")
    artist  = song.get("artist", "–")
    song_id = song.get("id", "")
    already = bool(song.get("pdf_url"))
    match   = find_best_pdf_match(song, pdf_files)

    c_nr, c_song, c_pdf, c_actions = st.columns([1, 3, 4, 2])

    with c_nr:
        st.markdown(f"**{i}**")

    with c_song:
        st.markdown(f"**{title}**  \n{artist}")

    if match and match["score"] >= min_score:
        score = int(match["score"])
        color = "green" if score >= 70 else "orange" if score >= 50 else "red"

        with c_pdf:
            pdf_html = (
                f'''<a href="{match["webViewLink"]}" target="_blank" '''
                f'''style="color:{color}; text-decoration:none; font-weight:500;">'''
                f'''{match["name"]}</a>'''
                f'''<br><span style="color:#888; font-size:0.82em;">Pisteet: {score}%</span>'''
            )
            st.markdown(pdf_html, unsafe_allow_html=True)

        with c_actions:
            if already:
                st.caption("✅ Tallennettu")
                if st.button("🗑️ Poista", key=f"rm_{song_id}_{i}"):
                    try:
                        remove_pdf_from_song(song_id)
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Virhe poistossa: {e}")
            else:
                if st.button("💾 Tallenna", key=f"save_{song_id}_{i}"):
                    try:
                        save_pdf_to_song(song_id, match["webViewLink"], match["name"])
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Virhe tallennuksessa: {e}")
    else:
        with c_pdf:
            st.caption("– ei tarpeeksi hyvää osumaa –")
        with c_actions:
            st.caption("")

    st.divider()

# ── Tilastot ──────────────────────────────────────────────────────────────────
saved_count = sum(1 for s in songs if s.get("pdf_url"))
missing_count = len(songs) - saved_count
pct = int(saved_count / len(songs) * 100) if songs else 0

st.subheader("📊 Tilanne")
m1, m2, m3 = st.columns(3)
m1.metric("✅ Tallennettu", saved_count)
m2.metric("❌ Puuttuu PDF", missing_count)
m3.metric("📈 Valmis", f"{pct} %")
