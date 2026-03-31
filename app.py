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
        background: #1e1e2e;
        border: 1px solid #44475a;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 10px;
    }
    .song-number {
        font-size: 2rem;
        font-weight: 900;
        color: #bd93f9;
        min-width: 48px;
        display: inline-block;
    }
    .song-title { font-size: 1.2rem; font-weight: 700; color: #f8f8f2; }
    .song-key {
        background: #44475a; color: #50fa7b;
        border-radius: 6px; padding: 2px 10px;
        font-size: 0.9rem; font-family: monospace; font-weight: bold;
    }
    .trans-badge {
        background: #ff79c6; color: #282a36;
        border-radius: 6px; padding: 2px 10px;
        font-size: 0.85rem; font-weight: bold; margin-left: 8px;
    }
    .capo-badge {
        background: #ffb86c; color: #282a36;
        border-radius: 6px; padding: 2px 10px;
        font-size: 0.85rem; font-weight: bold; margin-left: 8px;
    }
    @media (max-width: 600px) {
        .song-title { font-size: 1rem; }
        .song-number { font-size: 1.5rem; }
    }
</style>
""", unsafe_allow_html=True)

# ── PARSER ──────────────────────────────────────────────
def parse_setlist(text: str) -> list:
    setlist = []
    pattern = r"(\d+)[.\)]\s+(.+?)\s*\|\s*([A-Ga-g][#b]?m?)(.*)$"
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
                "numero":     int(match.group(1)),
                "biisi":      match.group(2).strip(),
                "savelaji":   match.group(3).strip(),
                "transponoi": trans.group(1) if trans else None,
                "capo":       int(capo.group(1)) if capo else None,
            })
        else:
            simple = re.match(r"(\d+)[.\)]\s+(.+)$", line)
            if simple:
                setlist.append({
                    "numero": int(simple.group(1)),
                    "biisi":  simple.group(2).strip(),
                    "savelaji": None, "transponoi": None, "capo": None,
                })
    return sorted(setlist, key=lambda x: x["numero"])

# ── PDF-NÄYTTÖ ───────────────────────────────────────────
def show_pdf(pdf_bytes: bytes):
    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    st.markdown(
        f'''<iframe src="data:application/pdf;base64,{b64}"
            width="100%" height="700px"
            style="border-radius:8px;border:1px solid #44475a;">
        </iframe>''',
        unsafe_allow_html=True
    )

# ── PDF-TEKSTI ───────────────────────────────────────────
def read_pdf_text(file) -> str:
    try:
        import fitz
        doc = fitz.open(stream=file.read(), filetype="pdf")
        return "\n".join(page.get_text("text") for page in doc)
    except ImportError:
        st.error("Asenna PyMuPDF: pip install pymupdf")
        return ""

# ════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════
st.title("🎸 Keikkasetti Manager")

tab_set, tab_drive, tab_settings = st.tabs(["📋 Setlista", "☁️ Google Drive", "⚙️ Asetukset"])

# ── TAB 1: SETLISTA ──────────────────────────────────────
with tab_set:

    with st.expander("📂 Syötä setlista", expanded=True):
        col1, col2 = st.columns([1, 1])
        with col1:
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
        raw_text = (uploaded_list.read().decode("utf-8")
                    if uploaded_list.type == "text/plain"
                    else read_pdf_text(uploaded_list))
        st.success(f"✅ {uploaded_list.name} ladattu")
    else:
        raw_text = manual

    setlist = parse_setlist(raw_text)
    if not setlist:
        st.warning("Ei tunnistettuja biisejä — tarkista formaatti.")
        st.stop()

    # Metriikat
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🎵 Biisiä",        len(setlist))
    c2.metric("🔄 Transponoitavia", sum(1 for x in setlist if x["transponoi"]))
    c3.metric("🎸 Kapotasto",      sum(1 for x in setlist if x["capo"]))
    c4.metric("📄 PDF:t ladattu",  sum(1 for x in st.session_state.get("pdfs", {}).items()))

    st.markdown("---")

    # PDF-liitäntä
    if "pdfs" not in st.session_state:
        st.session_state["pdfs"] = {}

    with st.expander("📎 Liitä PDF-tiedostot biiseille"):
        cols = st.columns(min(len(setlist), 3))
        for i, item in enumerate(setlist):
            with cols[i % 3]:
                f = st.file_uploader(
                    f"{item['numero']}. {item['biisi']}",
                    type=["pdf"], key=f"pdf_{item['numero']}"
                )
                if f:
                    st.session_state["pdfs"][item["numero"]] = f.read()

    st.markdown("### 🎶 Setlista")

    # Kortit
    for item in setlist:
        has_pdf = item["numero"] in st.session_state.get("pdfs", {})
        icon    = "📄" if has_pdf else "📭"
        label   = f"{item['numero']}. {item['biisi']}  {icon}"

        key_b   = f"<span class=\"song-key\">{item['savelaji']}</span>"   if item["savelaji"]   else ""
        trans_b = f"<span class=\"trans-badge\">🔄 → {item['transponoi']}</span>" if item["transponoi"] else ""
        capo_b  = f"<span class=\"capo-badge\">🎸 capo {item['capo']}</span>"     if item["capo"]       else ""

        with st.expander(label):
            st.markdown(
                f'''<div class="song-card">
                    <span class="song-number">{item["numero"]}</span>&nbsp;&nbsp;
                    <span class="song-title">{item["biisi"]}</span>&nbsp;&nbsp;
                    {key_b}{trans_b}{capo_b}
                </div>''',
                unsafe_allow_html=True
            )
            if has_pdf:
                show_pdf(st.session_state["pdfs"][item["numero"]])
            else:
                st.info("📭 Ei PDF:ää vielä. Liitä yllä tai hae Google Drivesta.")

# ── TAB 2: GOOGLE DRIVE ─────────────────────────────────
with tab_drive:
    st.subheader("☁️ Google Drive -integraatio")
    st.info("🔜 Rakennetaan seuraavassa vaiheessa.")
    st.markdown("""
    **Tulossa:**
    - Google OAuth2 -kirjautuminen
    - Drive-kansion automaattinen haku biisinnimellä
    - Tiedostojen automaattinen numerointi ja lataus
    """)

# ── TAB 3: ASETUKSET ─────────────────────────────────────
with tab_settings:
    st.subheader("🔄 Transponointi")
    st.info("🔜 Rakennetaan vaiheessa 4.")
    st.markdown("""
    **Tulossa:**
    - Sointujen automaattinen tunnistus PDF:stä
    - Transponointi halutulle sävellajille
    - Uuden PDF:n tallennus
    """)
    st.subheader("ℹ️ Tietoa")
    st.markdown("""
    **Keikkasetti Manager v0.2**
    - Parseri: TXT ja PDF setlistat
    - PDF-viewer: suoraan kortissa
    - Google Drive: tulossa
    - Transponointi: tulossa
    """)
