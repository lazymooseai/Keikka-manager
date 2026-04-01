import streamlit as st
import re
import base64

st.set_page_config(
    page_title="Keikkasetti Manager",
    page_icon="🎸",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .song-card {
        background:#1e1e2e; border:1px solid #44475a;
        border-radius:12px; padding:16px 20px; margin-bottom:10px;
    }
    .song-number { font-size:2rem; font-weight:900; color:#bd93f9;
                   min-width:48px; display:inline-block; }
    .song-title  { font-size:1.2rem; font-weight:700; color:#f8f8f2; }
    .song-key    { background:#44475a; color:#50fa7b; border-radius:6px;
                   padding:2px 10px; font-size:0.9rem; font-family:monospace; font-weight:bold; }
    .trans-badge { background:#ff79c6; color:#282a36; border-radius:6px;
                   padding:2px 10px; font-size:0.85rem; font-weight:bold; margin-left:8px; }
    .capo-badge  { background:#ffb86c; color:#282a36; border-radius:6px;
                   padding:2px 10px; font-size:0.85rem; font-weight:bold; margin-left:8px; }
    .match-good  { color:#50fa7b; font-weight:bold; }
    .match-ok    { color:#ffb86c; font-weight:bold; }
    .match-none  { color:#ff5555; font-weight:bold; }
    @media (max-width:600px) {
        .song-title { font-size:1rem; }
        .song-number { font-size:1.5rem; }
    }
</style>
""", unsafe_allow_html=True)


# ── PARSER ─────────────────────────────────────────────────────────────
def parse_setlist(text: str) -> list:
    setlist = []
    pattern = r"(\d+)[.\)]\s+(.+?)\s*\|\s*([A-Ga-g][#b]?m?)(.*)\$"
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        match = re.match(pattern, line)
        if match:
            extra = match.group(4).strip()
            trans = re.search(r"->\s*([A-Ga-g][#b]?m?)", extra)
            capo  = re.search(r"capo\s*(\d+)", extra, re.IGNORECASE)
            setlist.append({
                "numero": int(match.group(1)), "biisi": match.group(2).strip(),
                "savelaji": match.group(3).strip(),
                "transponoi": trans.group(1) if trans else None,
                "capo": int(capo.group(1)) if capo else None,
            })
        else:
            simple = re.match(r"(\d+)[.\)]\s+(.+)\$", line)
            if simple:
                setlist.append({
                    "numero": int(simple.group(1)), "biisi": simple.group(2).strip(),
                    "savelaji": None, "transponoi": None, "capo": None,
                })
    return sorted(setlist, key=lambda x: x["numero"])


# ── PDF → KUVAT ─────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def pdf_to_images(pdf_bytes: bytes) -> list:
    import fitz
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        mat = fitz.Matrix(1.5, 1.5)
        pix = page.get_pixmap(matrix=mat)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def read_pdf_text(file) -> str:
    try:
        import fitz
        doc = fitz.open(stream=file.read(), filetype="pdf")
        return "\n".join(page.get_text("text") for page in doc)
    except Exception as e:
        st.error(f"PDF-luku epäonnistui: {e}")
        return ""


def download_link(pdf_bytes: bytes, filename: str):
    b64 = base64.b64encode(pdf_bytes).decode()
    st.markdown(
        f'''<a href="data:application/pdf;base64,{b64}" download="{filename}"
            style="background:#6272a4;color:#f8f8f2;padding:6px 16px;
                   border-radius:6px;text-decoration:none;font-size:0.9rem;">
            ⬇️ Lataa PDF
        </a><br><br>''', unsafe_allow_html=True
    )


# ── DRIVE-FUNKTIOT ──────────────────────────────────────────────────────
def drive_available() -> bool:
    try:
        return "gcp_service_account" in st.secrets
    except Exception:
        return False


@st.cache_resource
def get_drive_service():
    from googleapiclient.discovery import build
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)


@st.cache_data(ttl=300)
def list_drive_pdfs(folder_id: str) -> list:
    service = get_drive_service()
    results = service.files().list(
        q=f"\'{folder_id}\' in parents and mimeType=\'application/pdf\' and trashed=false",
        fields="files(id, name, size)",
        pageSize=200
    ).execute()
    return results.get("files", [])


def find_best_match(song_name: str, drive_files: list, threshold: int = 60):
    from rapidfuzz import process, fuzz
    if not drive_files:
        return None
    names = [f["name"].replace(".pdf", "").replace("_", " ") for f in drive_files]
    match = process.extractOne(
        song_name, names,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=threshold
    )
    if match:
        _, score, idx = match
        return {"file": drive_files[idx], "score": score}
    return None


@st.cache_data(show_spinner=False)
def download_drive_pdf(file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    import io
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


# ════════════════════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════════════════════
st.title("🎸 Keikkasetti Manager")

if "pdfs" not in st.session_state:
    st.session_state["pdfs"] = {}

tab_set, tab_drive, tab_settings = st.tabs(["📋 Setlista", "☁️ Google Drive", "⚙️ Asetukset"])

# ── TAB 1: SETLISTA ──────────────────────────────────────────────────────
with tab_set:

    with st.expander("📂 Syötä setlista", expanded=True):
        col1, col2 = st.columns([1, 1])
        with col1:
            st.caption("⚠️ Tähän vain SETLISTA-tiedosto, ei nuotteja")
            uploaded_list = st.file_uploader(
                "Lataa setlista (TXT tai PDF)",
                type=["txt", "pdf"], key="setlist_file"
            )
        with col2:
            default_txt = """1. Kapteeni Tom | D
2. Hotel California | Bm -> Am
3. Wish You Were Here | G (capo 2)
4. Sultans of Swing | Dm
5. Comfortably Numb | Bm"""
            manual = st.text_area("Tai kirjoita tähän", value=default_txt, height=160)

    raw_text = ""
    if uploaded_list:
        if uploaded_list.type == "text/plain":
            raw_text = uploaded_list.read().decode("utf-8")
        else:
            raw_text = read_pdf_text(uploaded_list)
        st.success(f"✅ {uploaded_list.name} ladattu")
    else:
        raw_text = manual

    setlist = parse_setlist(raw_text)
    if not setlist:
        st.warning("Ei tunnistettuja biisejä — tarkista formaatti.")
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🎵 Biisiä",         len(setlist))
    c2.metric("🔄 Transponoitavia", sum(1 for x in setlist if x["transponoi"]))
    c3.metric("🎸 Kapotasto",       sum(1 for x in setlist if x["capo"]))
    c4.metric("📄 PDF:t ladattu",   len(st.session_state["pdfs"]))
    st.markdown("---")

    with st.expander("📎 Liitä PDF-tiedostot manuaalisesti"):
        st.caption("Käytä tätä jos Google Drive ei ole käytössä")
        cols = st.columns(min(len(setlist), 3))
        for i, item in enumerate(setlist):
            with cols[i % 3]:
                f = st.file_uploader(
                    f"{item['numero']}. {item['biisi']}",
                    type=["pdf"], key=f"pdf_upload_{item['numero']}"
                )
                if f is not None:
                    raw_pdf = f.read()
                    with st.spinner("Käsitellään..."):
                        imgs = pdf_to_images(raw_pdf)
                    st.session_state["pdfs"][item["numero"]] = {
                        "bytes": raw_pdf, "filename": f.name,
                        "images": imgs, "pages": len(imgs),
                        "source": "manual"
                    }
                    st.success(f"✅ {len(imgs)} sivu(a)")

    st.markdown("### 🎶 Setlista")
    for item in setlist:
        num     = item["numero"]
        has_pdf = num in st.session_state["pdfs"]
        icon    = "📄" if has_pdf else "📭"

        key_b   = f'<span class="song-key">{item["savelaji"]}</span>'           if item["savelaji"]   else ""
        trans_b = f'<span class="trans-badge">🔄 → {item["transponoi"]}</span>' if item["transponoi"] else ""
        capo_b  = f'<span class="capo-badge">🎸 capo {item["capo"]}</span>'     if item["capo"]       else ""

        with st.expander(f"{num}. {item['biisi']}  {icon}"):
            st.markdown(
                f'''<div class="song-card">
                    <span class="song-number">{num}</span>&nbsp;&nbsp;
                    <span class="song-title">{item["biisi"]}</span>&nbsp;&nbsp;
                    {key_b}{trans_b}{capo_b}
                </div>''', unsafe_allow_html=True
            )
            if has_pdf:
                pdf_obj = st.session_state["pdfs"][num]
                src = "☁️ Drive" if pdf_obj.get("source") == "drive" else "📁 Manuaalinen"
                st.caption(f"{src} — {pdf_obj['filename']} — {pdf_obj['pages']} sivu(a)")
                download_link(pdf_obj["bytes"], pdf_obj["filename"])
                for idx, img in enumerate(pdf_obj["images"]):
                    st.image(img, caption=f"Sivu {idx+1}", width="stretch")
            else:
                st.info("📭 Ei PDF:ää — liitä manuaalisesti tai hae Drive-välilehdeltä.")

# ── TAB 2: GOOGLE DRIVE ──────────────────────────────────────────────────
with tab_drive:
    st.subheader("☁️ Google Drive -integraatio")

    if not drive_available():
        st.warning("""
        **Google Drive ei ole vielä kytketty.**

        Lisää service account -avaimet Streamlit Cloudiin:
        1. Avaa sovelluksesi Streamlit Cloudissa
        2. Paina **⋮ → Settings → Secrets**
        3. Liitä secrets.toml sisältö
        """)
    else:
        folder_id = st.secrets["drive"]["folder_id"]

        col_a, col_b = st.columns([2, 1])
        with col_a:
            threshold = st.slider(
                "Nimien samankaltaisuuden kynnys (%)",
                min_value=40, max_value=95, value=65,
                help="Laske jos biisiä ei löydy automaattisesti"
            )
        with col_b:
            st.metric("Kansio-ID", folder_id[:12] + "...")

        if st.button("🔍 Hae PDF:t Drivesta koko setlistalle", type="primary"):
            with st.spinner("Haetaan Drive-kansiosta..."):
                try:
                    drive_files = list_drive_pdfs(folder_id)
                except Exception as e:
                    st.error(f"Drive-yhteys epäonnistui: {e}")
                    st.stop()

            if not drive_files:
                st.error("Drive-kansiossa ei PDF-tiedostoja tai kansio-ID on väärä.")
                st.stop()

            st.success(f"✅ Drive-kansiossa {len(drive_files)} PDF-tiedostoa")
            st.session_state["drive_files"] = drive_files
            st.markdown("---")

        if "drive_files" in st.session_state:
            drive_files = st.session_state["drive_files"]
            current_setlist = parse_setlist(raw_text if raw_text else default_txt)

            for item in current_setlist:
                col_name, col_match, col_action = st.columns([2, 2, 1])
                match = find_best_match(item["biisi"], drive_files, threshold)

                with col_name:
                    st.markdown(f"**{item['numero']}. {item['biisi']}**")
                with col_match:
                    if match:
                        score = match["score"]
                        cls   = "match-good" if score >= 80 else "match-ok"
                        st.markdown(
                            f'<span class="{cls}">✅ {match["file"]["name"]} ({score:.0f}%)</span>',
                            unsafe_allow_html=True
                        )
                    else:
                        st.markdown('<span class="match-none">❌ Ei löydy</span>', unsafe_allow_html=True)
                with col_action:
                    if match:
                        if st.button("⬇️", key=f"dl_{item['numero']}",
                                     help=f"Lataa {match['file']['name']}"):
                            with st.spinner("Ladataan..."):
                                pdf_bytes = download_drive_pdf(match["file"]["id"])
                                imgs = pdf_to_images(pdf_bytes)
                            st.session_state["pdfs"][item["numero"]] = {
                                "bytes": pdf_bytes,
                                "filename": match["file"]["name"],
                                "images": imgs,
                                "pages": len(imgs),
                                "source": "drive"
                            }
                            st.rerun()

            st.markdown("---")
            if st.button("⬇️ Lataa KAIKKI löydetyt automaattisesti", type="primary"):
                progress = st.progress(0)
                found = [item for item in current_setlist
                         if find_best_match(item["biisi"], drive_files, threshold)]
                for i, item in enumerate(current_setlist):
                    match = find_best_match(item["biisi"], drive_files, threshold)
                    if match:
                        with st.spinner(f"Ladataan: {item['biisi']}..."):
                            pdf_bytes = download_drive_pdf(match["file"]["id"])
                            imgs = pdf_to_images(pdf_bytes)
                        st.session_state["pdfs"][item["numero"]] = {
                            "bytes": pdf_bytes,
                            "filename": match["file"]["name"],
                            "images": imgs,
                            "pages": len(imgs),
                            "source": "drive"
                        }
                    progress.progress((i + 1) / len(current_setlist))
                st.success(f"✅ {len(found)}/{len(current_setlist)} biisiä ladattu! Siirry Setlista-välilehdelle.")
                st.rerun()

# ── TAB 3: ASETUKSET ─────────────────────────────────────────────────────
with tab_settings:
    st.subheader("🔄 Transponointi")
    st.info("🔜 Rakennetaan vaiheessa 5.")
    st.caption("Keikkasetti Manager v0.6 — Google Drive integraatio")
