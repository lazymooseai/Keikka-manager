"""
app.py — Keikka Manager
Streamlit-sovellus keikkojen setlistien hallintaan + Google Drive PDF-integraatio.
Versio: 2.0 — Korjaus: Drive-matchit tallennetaan Supabaseen, setlist näyttää PDF-statuksen.
"""

import streamlit as st
import json
import os
from supabase import create_client, Client
from googleapiclient.discovery import build
from google.oauth2 import service_account
from rapidfuzz import fuzz, process

# ─────────────────────────────────────────────────────────────
# Sivukonfiguraatio
# ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Keikka Manager",
    page_icon="🎸",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────
# Supabase-yhteys
# ─────────────────────────────────────────────────────────────

@st.cache_resource
def get_supabase() -> Client:
    url  = st.secrets["supabase"]["url"]
    key  = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = get_supabase()

# ─────────────────────────────────────────────────────────────
# Google Drive -yhteys
# ─────────────────────────────────────────────────────────────

@st.cache_resource
def get_drive_service():
    """Palauttaa Google Drive API -clientin service account -avaimella."""
    creds_json = st.secrets.get("google_service_account", None)
    if not creds_json:
        return None
    creds_dict = json.loads(creds_json) if isinstance(creds_json, str) else dict(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return build("drive", "v3", credentials=creds)

drive_service = get_drive_service()

# ─────────────────────────────────────────────────────────────
# Tietokantafunktiot
# ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def fetch_setlists() -> list:
    res = supabase.table("setlists").select("*").order("date", desc=True).execute()
    return res.data or []


@st.cache_data(ttl=30)
def fetch_songs(setlist_id: str) -> list:
    res = (
        supabase.table("songs")
        .select("id, position, title, artist, key, bpm, notes, pdf_url, pdf_filename, pdf_score")
        .eq("setlist_id", setlist_id)
        .order("position")
        .execute()
    )
    return res.data or []


def save_pdf_to_db(song_id: str, pdf_url: str, pdf_filename: str, score: int) -> bool:
    """Tallentaa Drive-haun löytämän PDF-matchin Supabaseen."""
    try:
        supabase.table("songs").update({
            "pdf_url":      pdf_url,
            "pdf_filename": pdf_filename,
            "pdf_score":    score,
        }).eq("id", song_id).execute()
        fetch_songs.clear()  # Tyhjennä cache
        return True
    except Exception as e:
        st.error(f"❌ Tallennus epäonnistui: {e}")
        return False


def remove_pdf_from_db(song_id: str) -> bool:
    """Poistaa PDF-linkin biisiltä."""
    try:
        supabase.table("songs").update({
            "pdf_url":      None,
            "pdf_filename": None,
            "pdf_score":    None,
        }).eq("id", song_id).execute()
        fetch_songs.clear()
        return True
    except Exception as e:
        st.error(f"❌ PDF:n poisto epäonnistui: {e}")
        return False


def create_setlist(name: str, date: str, venue: str) -> dict | None:
    try:
        res = supabase.table("setlists").insert({
            "name": name, "date": date, "venue": venue
        }).execute()
        fetch_setlists.clear()
        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"❌ Setlisti-luonti epäonnistui: {e}")
        return None


def add_song(setlist_id: str, title: str, artist: str, position: int) -> dict | None:
    try:
        res = supabase.table("songs").insert({
            "setlist_id": setlist_id,
            "title":      title,
            "artist":     artist,
            "position":   position,
        }).execute()
        fetch_songs.clear()
        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"❌ Biisin lisäys epäonnistui: {e}")
        return None


def update_song_field(song_id: str, field: str, value) -> bool:
    try:
        supabase.table("songs").update({field: value}).eq("id", song_id).execute()
        fetch_songs.clear()
        return True
    except Exception as e:
        st.error(f"❌ Päivitys epäonnistui: {e}")
        return False


def delete_song(song_id: str) -> bool:
    try:
        supabase.table("songs").delete().eq("id", song_id).execute()
        fetch_songs.clear()
        return True
    except Exception as e:
        st.error(f"❌ Poisto epäonnistui: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# Google Drive -hakufunktiot
# ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def list_drive_pdfs(folder_id: str | None = None) -> list:
    """Listaa kaikki PDF-tiedostot Google Drivesta."""
    if not drive_service:
        return []
    query = "mimeType='application/pdf' and trashed=false"
    if folder_id:
        query += f" and '{folder_id}' in parents"
    results = []
    page_token = None
    while True:
        resp = drive_service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, webViewLink, webContentLink)",
            pageSize=200,
            pageToken=page_token,
        ).execute()
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


def find_best_pdf_match(song: dict, pdf_files: list, threshold: int = 50) -> dict | None:
    """Etsii parhaiten sopivan PDF-tiedoston biisille fuzzy-matchingilla."""
    if not pdf_files:
        return None
    search_query = f"{song.get('title', '')} {song.get('artist', '')}".strip()
    names  = [f["name"] for f in pdf_files]
    result = process.extractOne(
        search_query,
        names,
        scorer=fuzz.token_set_ratio,
        score_cutoff=threshold,
    )
    if result:
        matched_name, score, idx = result
        return {**pdf_files[idx], "score": score}
    return None


# ─────────────────────────────────────────────────────────────
# UI-komponentit
# ─────────────────────────────────────────────────────────────

def pdf_status_badge(song: dict) -> str:
    """Palauttaa PDF-statuksen HTML-merkkijonona otsikkoon."""
    if song.get("pdf_url"):
        score = song.get("pdf_score", 0) or 0
        color = "#2ecc71" if score >= 70 else "#f39c12" if score >= 50 else "#3498db"
        return f' <span style="font-size:0.75em; color:{color}; font-weight:500">📄</span>'
    return ' <span style="font-size:0.75em; color:#999">📋</span>'


def render_song_row(song: dict, index: int):
    """Renderöi yhden biisin setlistissä expanderina."""
    title  = song.get("title", "—")
    artist = song.get("artist", "—")
    pdf_ok = bool(song.get("pdf_url"))
    icon   = "📄" if pdf_ok else "📋"

    label = f"{icon}  {index}. {title} — {artist}"

    with st.expander(label, expanded=False):
        st.markdown(f"### {index}&nbsp;&nbsp;{title} — {artist}")
        st.divider()

        # Metadata
        c1, c2, c3 = st.columns(3)
        with c1:
            new_key = st.text_input("Sävellaji", value=song.get("key") or "", key=f"key_{song['id']}")
            if new_key != (song.get("key") or ""):
                update_song_field(song["id"], "key", new_key)
        with c2:
            new_bpm = st.text_input("Tempo (BPM)", value=str(song.get("bpm") or ""), key=f"bpm_{song['id']}")
            if new_bpm.isdigit() and int(new_bpm) != (song.get("bpm") or 0):
                update_song_field(song["id"], "bpm", int(new_bpm))
        with c3:
            new_notes = st.text_input("Muistiinpanot", value=song.get("notes") or "", key=f"notes_{song['id']}")
            if new_notes != (song.get("notes") or ""):
                update_song_field(song["id"], "notes", new_notes)

        st.divider()

        # PDF-osio
        st.markdown("**Sointulehti (PDF)**")
        pdf_url      = song.get("pdf_url")
        pdf_filename = song.get("pdf_filename")
        pdf_score    = song.get("pdf_score")

        if pdf_url:
            col_a, col_b = st.columns([4, 1])
            with col_a:
                score_txt = f" ({pdf_score}%)" if pdf_score else ""
                st.markdown(
                    f'✅ <a href="{pdf_url}" target="_blank">'
                    f'{pdf_filename or "Avaa PDF"}</a>'
                    f'<span style="color:#999; font-size:0.85em">{score_txt}</span>',
                    unsafe_allow_html=True,
                )
            with col_b:
                if st.button("🗑️", key=f"delpdf_{song['id']}", help="Poista PDF-linkki"):
                    if remove_pdf_from_db(song["id"]):
                        st.rerun()
        else:
            st.info("📋 Ei PDF:ää — liitä manuaalisesti tai hae Drive-välilehdeltä.")

            # Manuaalinen URL-liitäntä
            manual_url = st.text_input(
                "Liitä Drive-URL manuaalisesti",
                placeholder="https://drive.google.com/...",
                key=f"manurl_{song['id']}",
            )
            if manual_url and st.button("💾 Tallenna", key=f"mansave_{song['id']}"):
                fname = manual_url.split("/")[-1].split("?")[0] or "PDF"
                if save_pdf_to_db(song["id"], manual_url, fname, 100):
                    st.success("✅ Tallennettu!")
                    st.rerun()

        st.divider()

        # Poista biisi
        if st.button("🗑️ Poista biisi", key=f"delsong_{song['id']}", type="secondary"):
            if delete_song(song["id"]):
                st.rerun()


# ─────────────────────────────────────────────────────────────
# SIVUPALKKI
# ─────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🎸 Keikka Manager")
    st.divider()

    setlists = fetch_setlists()

    # Setlisti-valinta
    if setlists:
        options = {f"{s['name']} — {s.get('date', '')}": s["id"] for s in setlists}
        selected_label = st.selectbox(
            "Valitse setlisti",
            list(options.keys()),
            key="setlist_selector",
        )
        active_setlist_id   = options[selected_label]
        active_setlist_data = next(s for s in setlists if s["id"] == active_setlist_id)
    else:
        st.warning("Ei setlistejä. Luo uusi alta.")
        active_setlist_id   = None
        active_setlist_data = None

    st.divider()

    # Uusi setlisti
    with st.expander("➕ Uusi setlisti"):
        new_name  = st.text_input("Nimi", placeholder="Kesäkeikka 2026")
        new_date  = st.date_input("Päivämäärä")
        new_venue = st.text_input("Paikka", placeholder="Ravintola Musiikki")
        if st.button("Luo setlisti", type="primary"):
            if new_name:
                sl = create_setlist(new_name, str(new_date), new_venue)
                if sl:
                    st.success(f"✅ Luotu: {new_name}")
                    st.rerun()

    # Drive-kansion ID
    st.divider()
    st.markdown("**⚙️ Google Drive -asetukset**")
    drive_folder_id = st.text_input(
        "Kansion ID (valinnainen)",
        value=st.session_state.get("drive_folder_id", ""),
        placeholder="1BxiMVs0XRA...",
        key="drive_folder_id",
        help="Jätä tyhjäksi hakuun koko Drivesta",
    )

    # Match-kynnysarvo
    threshold = st.slider("Matchaus-kynnys (%)", 30, 90, 55, key="threshold")

# ─────────────────────────────────────────────────────────────
# PÄÄSISÄLTÖ
# ─────────────────────────────────────────────────────────────

if not active_setlist_id:
    st.info("👈 Valitse tai luo setlisti sivupalkista.")
    st.stop()

st.title(f"🎤 {active_setlist_data.get('name', 'Setlisti')}")
info_cols = st.columns(3)
info_cols[0].metric("Päivämäärä",  active_setlist_data.get("date", "—"))
info_cols[1].metric("Paikka",      active_setlist_data.get("venue", "—"))

songs = fetch_songs(active_setlist_id)
info_cols[2].metric("Biisejä", len(songs))

st.divider()

# Välilehdet
tab_list, tab_drive, tab_add = st.tabs(["📋 Setlisti", "🔍 Drive-haku", "➕ Lisää biisi"])

# ═══════════════════════════════════════════════════════════
# TAB 1: SETLISTI
# ═══════════════════════════════════════════════════════════

with tab_list:
    if not songs:
        st.info("Setlisti on tyhjä. Lisää biisejä Drive-haku- tai Lisää biisi -välilehdeltä.")
    else:
        # Tilastopalkki
        with_pdf    = sum(1 for s in songs if s.get("pdf_url"))
        without_pdf = len(songs) - with_pdf
        prog_col1, prog_col2 = st.columns([3, 1])
        with prog_col1:
            st.progress(with_pdf / len(songs) if songs else 0)
        with prog_col2:
            st.caption(f"📄 {with_pdf}/{len(songs)} PDF:llä")

        st.markdown("")
        for i, song in enumerate(songs, start=1):
            render_song_row(song, i)

# ═══════════════════════════════════════════════════════════
# TAB 2: DRIVE-HAKU
# ═══════════════════════════════════════════════════════════

with tab_drive:
    if not drive_service:
        st.error(
            "🔑 Google Drive -yhteyttä ei ole konfiguroitu. "
            "Lisää `google_service_account` JSON Streamlit Secretseihin."
        )
        st.stop()

    if not songs:
        st.info("Lisää biisejä ensin setlistiin.")
        st.stop()

    st.markdown("### 🔍 Hae PDF-sointulehtiä Google Drivesta")

    col_btn1, col_btn2 = st.columns([2, 2])
    run_search = col_btn1.button("🔍 Hae kaikki", type="primary")
    save_all   = col_btn2.button("💾 Tallenna kaikki löydetyt", type="secondary")

    if run_search or "drive_search_results" in st.session_state:
        with st.spinner("Haetaan PDF-tiedostoja Drivesta..."):
            pdf_files = list_drive_pdfs(folder_id=drive_folder_id or None)

        if not pdf_files:
            st.warning("⚠️ Drivesta ei löytynyt yhtään PDF-tiedostoa. Tarkista kansion ID ja oikeudet.")
            st.stop()

        st.caption(f"📁 Löytyi {len(pdf_files)} PDF:ää Drivesta")
        st.divider()

        results = []
        for i, song in enumerate(songs, start=1):
            title  = song.get("title", "—")
            artist = song.get("artist", "—")
            match  = find_best_pdf_match(song, pdf_files, threshold=threshold)

            col_nr, col_song, col_pdf, col_actions = st.columns([0.5, 2.5, 3, 2])

            with col_nr:
                st.markdown(f"**{i}**")
            with col_song:
                st.markdown(f"""**{title}**{artist}""")

            if match:
                results.append({
                    "song_id":      song["id"],
                    "pdf_url":      match["webViewLink"],
                    "pdf_filename": match["name"],
                    "score":        match["score"],
                })
                score   = int(match["score"])
                color   = "green" if score >= 70 else "orange" if score >= threshold else "red"
                already = bool(song.get("pdf_url"))

                with col_pdf:
                    st.markdown(
                        f'<a href="{match["webViewLink"]}" target="_blank" '
                        f'style="color:{color}">{match["name"]}</a>'
                        f' <span style="color:#888; font-size:0.85em">({score}%)</span>',
                        unsafe_allow_html=True,
                    )

                with col_actions:
                    if already:
                        st.caption("✅ Tallennettu")
                        if st.button("🔄", key=f"resave_{song['id']}", help="Päivitä uuteen matchiin"):
                            if save_pdf_to_db(
                                song["id"],
                                match["webViewLink"],
                                match["name"],
                                score,
                            ):
                                st.success("Päivitetty!")
                                st.rerun()
                    else:
                        if st.button(
                            "💾 Tallenna",
                            key=f"save_{song['id']}",
                            type="primary",
                        ):
                            if save_pdf_to_db(
                                song["id"],
                                match["webViewLink"],
                                match["name"],
                                score,
                            ):
                                st.success("✅ Tallennettu!")
                                st.rerun()
            else:
                with col_pdf:
                    st.caption("❌ Ei osumaa")
                with col_actions:
                    st.caption("—")

            st.session_state["drive_search_results"] = results

        # Tallenna kaikki kerralla
        if save_all and "drive_search_results" in st.session_state:
            all_results = st.session_state["drive_search_results"]
            saved = 0
            for r in all_results:
                if save_pdf_to_db(r["song_id"], r["pdf_url"], r["pdf_filename"], r["score"]):
                    saved += 1
            if saved:
                del st.session_state["drive_search_results"]
                st.success(f"✅ Tallennettu {saved}/{len(all_results)} PDF-matchäystä!")
                st.rerun()

    else:
        st.info("Paina **🔍 Hae kaikki** hakeaksesi sopivat PDF-tiedostot kaikille biiseille.")

        # Näytä nykyinen PDF-status
        st.markdown("**Nykyinen PDF-status:**")
        for i, song in enumerate(songs, start=1):
            title  = song.get("title", "—")
            artist = song.get("artist", "—")
            if song.get("pdf_url"):
                fname = song.get("pdf_filename") or "PDF"
                score = song.get("pdf_score")
                score_txt = f" ({score}%)" if score else ""
                st.markdown(
                    f"**{i}.** {title} — {artist}: "
                    f'✅ <a href="{song["pdf_url"]}" target="_blank">{fname}</a>'
                    f'<span style="color:#888; font-size:0.85em">{score_txt}</span>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"**{i}.** {title} — {artist}: 📋 Ei PDF:ää")

# ═══════════════════════════════════════════════════════════
# TAB 3: LISÄÄ BIISI
# ═══════════════════════════════════════════════════════════

with tab_add:
    st.markdown("### ➕ Lisää biisi setlistiin")

    a1, a2 = st.columns(2)
    new_title  = a1.text_input("Kappaleen nimi *", placeholder="Juna kulkee")
    new_artist = a2.text_input("Artisti *",        placeholder="Kari Tapio")
    new_pos    = st.number_input(
        "Järjestysnumero",
        min_value=1,
        max_value=len(songs) + 1,
        value=len(songs) + 1,
    )

    if st.button("Lisää biisi", type="primary"):
        if new_title and new_artist:
            song = add_song(active_setlist_id, new_title.strip(), new_artist.strip(), int(new_pos))
            if song:
                st.success(f"✅ Lisätty: {new_title} — {new_artist}")
                st.rerun()
        else:
            st.error("Täytä vähintään kappaleen nimi ja artisti.")

    # Bulk-lisäys CSV-muodossa
    st.divider()
    st.markdown("**Bulk-lisäys (yksi biisi per rivi: `Nimi;Artisti`)**")
    bulk_input = st.text_area(
        "Biisit",
        placeholder="Juna kulkee;Kari Tapio\nMuukalainen;Fredi",
        height=150,
        key="bulk_songs",
    )
    if st.button("Lisää kaikki"):
        if bulk_input.strip():
            lines  = [l.strip() for l in bulk_input.strip().splitlines() if ";" in l]
            added  = 0
            start  = len(songs) + 1
            for j, line in enumerate(lines):
                parts = line.split(";", 1)
                if len(parts) == 2:
                    t, a = parts[0].strip(), parts[1].strip()
                    if t and a:
                        if add_song(active_setlist_id, t, a, start + j):
                            added += 1
            if added:
                st.success(f"✅ Lisätty {added} biisiä.")
                st.rerun()
