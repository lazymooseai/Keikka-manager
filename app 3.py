import streamlit as st
import re
import base64

st.set_page_config(
    page_title="Keikkasetti Manager",
    page_icon="🎸",
    layout="wide",
    initial_sidebar_state="collapsed"
)

CSS = """
<style>
    .song-card { background:#1e1e2e; border:1px solid #44475a; border-radius:12px; padding:16px 20px; margin-bottom:10px; }
    .song-number { font-size:2rem; font-weight:900; color:#bd93f9; min-width:48px; display:inline-block; }
    .song-title  { font-size:1.2rem; font-weight:700; color:#f8f8f2; }
    .song-key    { background:#44475a; color:#50fa7b; border-radius:6px; padding:2px 10px; font-size:0.9rem; font-family:monospace; font-weight:bold; }
    .trans-badge { background:#ff79c6; color:#282a36; border-radius:6px; padding:2px 10px; font-size:0.85rem; font-weight:bold; margin-left:8px; }
    .capo-badge  { background:#ffb86c; color:#282a36; border-radius:6px; padding:2px 10px; font-size:0.85rem; font-weight:bold; margin-left:8px; }
    .match-good  { color:#50fa7b; font-weight:bold; }
    .match-ok    { color:#ffb86c; font-weight:bold; }
    .match-none  { color:#ff5555; font-weight:bold; }
</style>
"""

DEFAULT_SETLIST = """1. Kapteeni Tom | D
2. Hotel California | Bm -> Am
3. Wish You Were Here | G (capo 2)
4. Sultans of Swing | Dm
5. Comfortably Numb | Bm"""


def parse_setlist(text):
    setlist = []
    pattern = r"(\d+)[.\)]\s+(.+?)\s*\|\s*([A-Ga-g][#b]?m?)(.*)"
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(pattern, line)
        if m:
            extra = m.group(4).strip()
            trans = re.search(r"->\s*([A-Ga-g][#b]?m?)", extra)
            capo  = re.search(r"capo\s*(\d+)", extra, re.IGNORECASE)
            setlist.append({
                "numero": int(m.group(1)), "biisi": m.group(2).strip(),
                "savelaji": m.group(3).strip(),
                "transponoi": trans.group(1) if trans else None,
                "capo": int(capo.group(1)) if capo else None,
            })
        else:
            s = re.match(r"(\d+)[.\)]\s+(.+)", line)
            if s:
                setlist.append({
                    "numero": int(s.group(1)), "biisi": s.group(2).strip(),
                    "savelaji": None, "transponoi": None, "capo": None,
                })
    return sorted(setlist, key=lambda x: x["numero"])


@st.cache_data(show_spinner=False)
def pdf_to_images(pdf_bytes):
    import fitz
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def read_pdf_text(file):
    try:
        import fitz
        doc = fitz.open(stream=file.read(), filetype="pdf")
        return "\n".join(p.get_text("text") for p in doc)
    except Exception as e:
        st.error(f"PDF-luku epäonnistui: {e}")
        return ""


def download_link(pdf_bytes, filename):
    b64 = base64.b64encode(pdf_bytes).decode()
    st.markdown(
        f'<a href="data:application/pdf;base64,{b64}" download="{filename}"'
        f' style="background:#6272a4;color:#f8f8f2;padding:6px 16px;'
        f'border-radius:6px;text-decoration:none;font-size:0.9rem;">⬇️ Lataa PDF</a><br><br>',
        unsafe_allow_html=True
    )


def drive_available():
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
def list_drive_pdfs(folder_id):
    svc = get_drive_service()
    q = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
    res = svc.files().list(q=q, fields="files(id, name, size)", pageSize=200).execute()
    return res.get("files", [])


def find_best_match(song_name, drive_files, threshold=60):
    from rapidfuzz import process, fuzz
    if not drive_files:
        return None
    names = [f["name"].replace(".pdf", "").replace("_", " ") for f in drive_files]
    match = process.extractOne(song_name, names, scorer=fuzz.token_sort_ratio, score_cutoff=threshold)
    if match:
        _, score, idx = match
        return {"file": drive_files[idx], "score": score}
    return None


@st.cache_data(show_spinner=False)
def download_drive_pdf(file_id):
    from googleapiclient.http import MediaIoBaseDownload
    import io
    svc = get_drive_service()
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


# ════════════════════════════════════════════════════════
if "pdfs" not in st.session_state:
    st.session_state["pdfs"] = {}
if "raw_text" not in st.session_state:
    st.session_state["raw_text"] = DEFAULT_SETLIST

st.markdown(CSS, unsafe_allow_html=True)
st.title("🎸 Keikkasetti Manager")

tab_set, tab_drive, tab_settings = st.tabs(["📋 Setlista", "☁️ Google Drive", "⚙️ Asetukset"])

# ── SETLISTA ─────────────────────────────────────────────
with tab_set:
    with st.expander("📂 Syötä setlista", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.caption("⚠️ Tähän vain SETLISTA, ei nuotteja")
            uploaded = st.file_uploader("Lataa setlista (TXT/PDF)", type=["txt", "pdf"], key="setlist_file")
        with c2:
            manual = st.text_area("Tai kirjoita tähän", value=st.session_state["raw_text"], height=160)

    if uploaded:
        raw_text = uploaded.read().decode("utf-8") if uploaded.type == "text/plain" else read_pdf_text(uploaded)
        st.success(f"✅ {uploaded.name} ladattu")
    else:
        raw_text = manual

    st.session_state["raw_text"] = raw_text
    setlist = parse_setlist(raw_text)

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("🎵 Biisiä",   len(setlist))
    mc2.metric("🔄 Transponoi", sum(1 for x in setlist if x["transponoi"]))
    mc3.metric("🎸 Capo",      sum(1 for x in setlist if x["capo"]))
    mc4.metric("📄 PDF:t",     len(st.session_state["pdfs"]))
    st.markdown("---")

    if not setlist:
        st.warning("Ei tunnistettuja biisejä — tarkista formaatti (esim. '1. Biisi | D')")
    else:
        with st.expander("📎 Liitä PDF:t manuaalisesti"):
            cols = st.columns(min(len(setlist), 3))
            for i, item in enumerate(setlist):
                with cols[i % 3]:
                    f = st.file_uploader(f"{item['numero']}. {item['biisi']}", type=["pdf"], key=f"pu_{item['numero']}")
                    if f:
                        raw_pdf = f.read()
                        imgs = pdf_to_images(raw_pdf)
                        st.session_state["pdfs"][item["numero"]] = {
                            "bytes": raw_pdf, "filename": f.name, "images": imgs, "pages": len(imgs), "source": "manual"
                        }
                        st.success(f"✅ {len(imgs)} s.")

        st.markdown("### 🎶 Setlista")
        for item in setlist:
            num = item["numero"]
            has = num in st.session_state["pdfs"]
            icon = "📄" if has else "📭"
            kb = f'<span class="song-key">{item["savelaji"]}</span>' if item["savelaji"] else ""
            tb = f'<span class="trans-badge">🔄 → {item["transponoi"]}</span>' if item["transponoi"] else ""
            cb = f'<span class="capo-badge">🎸 capo {item["capo"]}</span>' if item["capo"] else ""
            with st.expander(f"{num}. {item['biisi']}  {icon}"):
                st.markdown(
                    f'<div class="song-card"><span class="song-number">{num}</span>&nbsp;&nbsp;'
                    f'<span class="song-title">{item["biisi"]}</span>&nbsp;&nbsp;{kb}{tb}{cb}</div>',
                    unsafe_allow_html=True
                )
                if has:
                    p = st.session_state["pdfs"][num]
                    src = "☁️ Drive" if p.get("source") == "drive" else "📁 Manuaalinen"
                    st.caption(f"{src} — {p['filename']} — {p['pages']} sivu(a)")
                    download_link(p["bytes"], p["filename"])
                    for idx, img in enumerate(p["images"]):
                        st.image(img, caption=f"Sivu {idx+1}", use_container_width=True)
                else:
                    st.info("📭 Ei PDF:ää — liitä manuaalisesti tai hae Drive-välilehdeltä.")

# ── GOOGLE DRIVE ─────────────────────────────────────────
with tab_drive:
    st.subheader("☁️ Google Drive -integraatio")

    if not drive_available():
        st.warning("**Google Drive ei ole kytketty.** Lisää secrets Streamlit Cloudiin.")
        st.code("""[gcp_service_account]
type                        = "service_account"
project_id                  = "magnetic-flare-470312-c4"
private_key_id              = "LISÄÄ_TÄHÄN"
private_key                 = "-----BEGIN RSA PRIVATE KEY-----\\nLISÄÄ_TÄHÄN\\n-----END RSA PRIVATE KEY-----\\n"
client_email                = "keikkamanager@magnetic-flare-470312-c4.iam.gserviceaccount.com"
client_id                   = "106781187829372201808"
auth_uri                    = "https://accounts.google.com/o/oauth2/auth"
token_uri                   = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url        = "https://www.googleapis.com/robot/v1/metadata/x509/keikkamanager%40magnetic-flare-470312-c4.iam.gserviceaccount.com"

[drive]
folder_id = "1Ur6z-_MaROp_CRaUGTMHrFxCygX6Lj_h"
""", language="toml")
    else:
        folder_id = st.secrets["drive"]["folder_id"]
        threshold = st.slider("Nimien samankaltaisuuden kynnys (%)", 40, 95, 65)

        if st.button("🔍 Hae PDF:t Drivesta", type="primary"):
            with st.spinner("Haetaan..."):
                try:
                    files = list_drive_pdfs(folder_id)
                    st.session_state["drive_files"] = files
                    st.success(f"✅ Löydettiin {len(files)} PDF-tiedostoa")
                except Exception as e:
                    st.error(f"Drive-yhteys epäonnistui: {e}")

        if "drive_files" in st.session_state:
            drive_files = st.session_state["drive_files"]
            cur = parse_setlist(st.session_state.get("raw_text", DEFAULT_SETLIST))
            st.markdown("---")
            for item in cur:
                cn, cm, ca = st.columns([2, 2, 1])
                match = find_best_match(item["biisi"], drive_files, threshold)
                with cn:
                    st.markdown(f"**{item['numero']}. {item['biisi']}**")
                with cm:
                    if match:
                        score = match["score"]
                        cls = "match-good" if score >= 80 else "match-ok"
                        st.markdown(f'<span class="{cls}">✅ {match["file"]["name"]} ({score:.0f}%)</span>', unsafe_allow_html=True)
                    else:
                        st.markdown('<span class="match-none">❌ Ei löydy</span>', unsafe_allow_html=True)
                with ca:
                    if match and st.button("⬇️", key=f"dl_{item['numero']}", help=match["file"]["name"]):
                        with st.spinner("Ladataan..."):
                            pb = download_drive_pdf(match["file"]["id"])
                            imgs = pdf_to_images(pb)
                        st.session_state["pdfs"][item["numero"]] = {
                            "bytes": pb, "filename": match["file"]["name"],
                            "images": imgs, "pages": len(imgs), "source": "drive"
                        }
                        st.rerun()

            st.markdown("---")
            if st.button("⬇️ Lataa KAIKKI löydetyt", type="primary"):
                bar = st.progress(0)
                for i, item in enumerate(cur):
                    match = find_best_match(item["biisi"], drive_files, threshold)
                    if match:
                        pb = download_drive_pdf(match["file"]["id"])
                        imgs = pdf_to_images(pb)
                        st.session_state["pdfs"][item["numero"]] = {
                            "bytes": pb, "filename": match["file"]["name"],
                            "images": imgs, "pages": len(imgs), "source": "drive"
                        }
                    bar.progress((i + 1) / len(cur))
                st.success("✅ Kaikki ladattu! Siirry Setlista-välilehdelle.")
                st.rerun()

# ── ASETUKSET ─────────────────────────────────────────────
with tab_settings:
    st.subheader("⚙️ Asetukset")
    st.info("🔜 Transponointi rakennetaan vaiheessa 5.")
    st.markdown("""
**Keikkasetti Manager v0.6.1**
- 📋 Setlista — selaa biisit, liitä PDF:t manuaalisesti
- ☁️ Google Drive — automaattinen PDF-haku & lataus
- ⚙️ Asetukset — tulossa: transponointi, viritys
    """)
    st.caption("lazymoose.ai")
