import streamlit as st
import re
import base64
import io

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
        font-size: 2rem; font-weight: 900;
        color: #bd93f9; min-width: 48px; display: inline-block;
    }
    .song-title  { font-size: 1.2rem; font-weight: 700; color: #f8f8f2; }
    .song-key    { background:#44475a; color:#50fa7b; border-radius:6px;
                   padding:2px 10px; font-size:0.9rem; font-family:monospace; font-weight:bold; }
    .trans-badge { background:#ff79c6; color:#282a36; border-radius:6px;
                   padding:2px 10px; font-size:0.85rem; font-weight:bold; margin-left:8px; }
    .capo-badge  { background:#ffb86c; color:#282a36; border-radius:6px;
                   padding:2px 10px; font-size:0.85rem; font-weight:bold; margin-left:8px; }
    @media (max-width:600px) {
        .song-title  { font-size:1rem; }
        .song-number { font-size:1.5rem; }
    }
</style>
""", unsafe_allow_html=True)


# ── PARSER ─────────────────────────────────────────────────────────────
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


# ── PDF → KUVAT ─────────────────────────────────────────────────────────
def pdf_to_images(pdf_bytes: bytes) -> list:
    import fitz
    images = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        images.append(img_bytes)
    doc.close()
    return images


# ── PDF-TEKSTI ──────────────────────────────────────────────────────────
def read_pdf_text(file) -> str:
    try:
        import fitz
        data = file.read()
        doc = fitz.open(stream=data, filetype="pdf")
        return "\n".join(page.get_text("text") for page in doc)
    except Exception as e:
        st.error(f"PDF-luku epäonnistui: {e}")
        return ""


# ── LATAUSLINKKI ────────────────────────────────────────────────────────
def download_link(pdf_bytes: bytes, filename: str):
    b64 = base64.b64encode(pdf_bytes).decode()
    st.markdown(
        f'''<a href="data:application/pdf;base64,{b64}" download="{filename}"
            style="background:#6272a4;color:#f8f8f2;padding:6px 16px;
                   border-radius:6px;text-decoration:none;font-size:0.9rem;">
            ⬇️ Lataa PDF
        </a><br><br>''',
        unsafe_allow_html=True
    )


# ════════════════════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════════════════════
st.title("🎸 Keikkasetti Manager")

if "pdfs" not in st.session_state:
    st.session_state["pdfs"] = {}

tab_set, tab_drive, tab_settings = st.tabs(["📋 Setlista", "☁️ Google Drive", "⚙️ Asetukset"])

with tab_set:

    # ── SETLISTAN SYÖTTÖ ────────────────────────────────────────────────
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

    # ── METRIIKAT ───────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🎵 Biisiä",           len(setlist))
    c2.metric("🔄 Transponoitavia",  sum(1 for x in setlist if x["transponoi"]))
    c3.metric("🎸 Kapotasto",        sum(1 for x in setlist if x["capo"]))
    c4.metric("📄 PDF:t ladattu",    len(st.session_state["pdfs"]))

    st.markdown("---")

    # ── PDF-LATAUS PER BIISI ─────────────────────────────────────────────
    with st.expander("📎 Liitä PDF-tiedostot biiseille"):
        cols = st.columns(min(len(setlist), 3))
        for i, item in enumerate(setlist):
            with cols[i % 3]:
                f = st.file_uploader(
                    f"{item['numero']}. {item['biisi']}",
                    type=["pdf"], key=f"pdf_upload_{item['numero']}"
                )
                if f is not None:
                    raw_pdf = f.read()
                    imgs    = pdf_to_images(raw_pdf)
                    st.session_state["pdfs"][item["numero"]] = {
                        "bytes":    raw_pdf,
                        "filename": f.name,
                        "images":   imgs,
                        "pages":    len(imgs)
                    }
                    st.success(f"✅ {len(imgs)} sivu(a)")

    st.markdown("### 🎶 Setlista")

    # ── BIISIKORTIT ──────────────────────────────────────────────────────
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
                </div>''',
                unsafe_allow_html=True
            )

            if has_pdf:
                pdf_obj = st.session_state["pdfs"][num]
                st.caption(f"📄 {pdf_obj['filename']} — {pdf_obj['pages']} sivu(a)")
                download_link(pdf_obj["bytes"], pdf_obj["filename"])

                # ✅ Streamlit 1.55+ käyttää width= parametria
                for idx, img in enumerate(pdf_obj["images"]):
                    st.image(img, caption=f"Sivu {idx+1}", width="stretch")
            else:
                st.info("📭 Ei PDF:ää — liitä yllä olevasta lataajasta.")

with tab_drive:
    st.subheader("☁️ Google Drive -integraatio")
    st.info("🔜 Rakennetaan seuraavassa vaiheessa.")

with tab_settings:
    st.subheader("🔄 Transponointi")
    st.info("🔜 Rakennetaan vaiheessa 4.")
    st.caption("Keikkasetti Manager v0.4")
