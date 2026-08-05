# app.py
# pyright: reportMissingImports=false
import importlib.util
import streamlit as st
import pandas as pd
import pyrebase
import os
import shutil
import re
import time
import json
import pydeck as pdk
from pathlib import Path
from process_data import processar_arquivos

# ==============================
# Firebase
# ==============================
FIREBASE_CONFIG = {
    "apiKey": "AIzaSyDjeRvV8yHAUmzDbiv2laM5tVM5iFXBByw",
    "authDomain": "monitora-arbo.firebaseapp.com",
    "projectId": "monitora-arbo",
    "storageBucket": "monitora-arbo.appspot.com",
    "messagingSenderId": "401575058454",
    "appId": "1:401575058454:web:52475e9a1be4acfe4fa937",
    "measurementId": "G-2CBGBT9JHG",
    "databaseURL": "https://monitora-arbo.firebaseio.com"
}
EMAIL_VE = "vigilanciaepidemiologicadsvii@gmail.com"
EMAIL_VA = "vigilanciaambientalds7@gmail.com"
EMAIL_ADMIN = "raquelmlacioli@gmail.com"

firebase = pyrebase.initialize_app(FIREBASE_CONFIG)
auth = firebase.auth()

def pode_visualizar(email): return email in [EMAIL_VA, EMAIL_VE]
def pode_editar(email): return email == EMAIL_VE
def email_valido(email): return re.match(r"[^@]+@[^@]+\.[^@]+", email)

# ==============================
# Imports opcionais (com flags)
# ==============================
_HAS_GEOPY=_HAS_FOLIUM=_HAS_SHAPELY=_HAS_FASTKML=_HAS_ALTAIR=False
try:
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
    _HAS_GEOPY=True
except Exception: pass
try:
    import folium
    from folium.plugins import MarkerCluster, FastMarkerCluster
    from streamlit_folium import st_folium
    _HAS_FOLIUM=True
except Exception: pass
try:
    from shapely.geometry import shape, Polygon, mapping
    from shapely.ops import unary_union
    _HAS_SHAPELY=True
except Exception: pass
try:
    from fastkml import kml as _fastkml  # type: ignore
    _HAS_FASTKML=True
except Exception: pass
try:
    import altair as alt  # type: ignore
    _HAS_ALTAIR=True
except Exception: pass

# ==============================
# Paths + fonte do contorno (assets/ ou URL)
# ==============================
BASE_DIR   = Path(__file__).resolve().parent
DATA_DIR   = BASE_DIR / "dados_salvos"
TEMP_DIR   = BASE_DIR / "temp_upload"
ASSETS_DIR = BASE_DIR / "assets"

DS7_SOURCE       = ASSETS_DIR / "ds7.geojson"
DS7_GEOJSON_PATH = DATA_DIR   / "ds7.geojson"
DS7_REMOTE_URL   = "https://raw.githubusercontent.com/raquelacioli/monitora-arbo/main/assets/ds7.geojson"

# ==============================
# Utilidades de dados
# ==============================
def remover_colunas_duplicadas(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame): return df
    return df.loc[:, ~df.columns.duplicated(keep='first')].copy()

def pick_nao_vazio(df: pd.DataFrame, prefer: str, fallback: str) -> pd.Series:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.Series([], dtype=object)
    pref = df[prefer] if prefer in df.columns else None
    fb   = df[fallback] if fallback in df.columns else None
    if pref is None and fb is None:
        return pd.Series([""]*len(df), index=df.index, dtype=object)
    if pref is None:
        return fb.fillna("").astype(str)
    if fb is None:
        return pref.fillna("").astype(str)
    pref_s = pref.fillna("").astype(str).str.strip()
    fb_s   = fb.fillna("").astype(str).str.strip()
    invalid = {"none","nan","nat","null","nonetype"}
    pref_s = pref_s.where(~pref_s.str.lower().isin(invalid) & (pref_s!=""), "")
    fb_s   = fb_s.where(~fb_s.str.lower().isin(invalid) & (fb_s!=""), "")
    return pref_s.where(pref_s!="", fb_s).fillna("")

def adicionar_endereco_br(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame): return df
    bairro = df["NM_BAIRRO"] if "NM_BAIRRO" in df.columns else pd.Series([""]*len(df), index=df.index)
    logr   = pick_nao_vazio(df, "NM_LOGRADO.1", "NM_LOGRADO")
    num    = pick_nao_vazio(df, "NU_NUMERO.1", "NU_NUMERO")
    df["ENDERECO_BR"] = (
        "Brasil, Pernambuco, Recife, "
        + bairro.fillna("").astype(str).str.strip() + ", "
        + logr.fillna("").astype(str).str.strip() + ", "
        + num.fillna("").astype(str).str.strip()
    )
    df["ENDERECO_BR"] = (
        df["ENDERECO_BR"]
        .str.replace(r"\s+,", ",", regex=True)
        .str.replace(r",\s*,", ", ", regex=True)
        .str.replace(r"(, )+$", "", regex=True)
        .str.replace(r",\s*,", ", ", regex=True)
    )
    return df

def filtrar_por_ultimos_dias(df: pd.DataFrame, coluna_data: str, dias: int) -> pd.DataFrame:
    if df is None or coluna_data not in df.columns: return df
    datas = pd.to_datetime(df[coluna_data], errors="coerce", dayfirst=True)
    limite = pd.Timestamp.today().normalize() - pd.Timedelta(days=dias)
    return df.loc[datas >= limite].copy()

def formatar_datas_para_str_ddmmaaaa(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame): return df
    df = df.copy()
    padroes = re.compile(r"(^(DT|DATA)_|_DT$|DATA|Data|data)")
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]) or padroes.search(col):
            s = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
            df[col] = s.dt.strftime("%d/%m/%Y")
    return df

# ==============================
# Epidemiologia: histograma por Semana ISO
# ==============================
def _add_epi_cols_local(df: pd.DataFrame, data_col: str = "DT_SIN_PRI") -> pd.DataFrame:
    if df is None or data_col not in df.columns: return df
    out = df.copy()
    datas = pd.to_datetime(out[data_col], errors="coerce", dayfirst=True)
    iso = datas.dt.isocalendar()
    out["ANO_ISO"] = iso["year"].astype("Int64")
    out["SEMANA_ISO"] = iso["week"].astype("Int64")
    return out

def plot_histograma_semana(df: pd.DataFrame, data_col: str = "DT_SIN_PRI", titulo: str = "Total de casos por Semana Epidemiológica"):
    if df is None or df.empty or data_col not in df.columns:
        st.info("Sem dados suficientes para o histograma de semanas.")
        return
    base = _add_epi_cols_local(df, data_col)
    tmp = base.dropna(subset=["SEMANA_ISO"])
    if tmp.empty:
        st.info("Sem semanas válidas para o histograma.")
        return
    agg = tmp.groupby("SEMANA_ISO", dropna=True).size().reset_index(name="casos").sort_values("SEMANA_ISO")
    if _HAS_ALTAIR:
        chart = (
            alt.Chart(agg)
            .mark_bar()
            .encode(
                x=alt.X("SEMANA_ISO:O", title="Semana Epidemiológica (ISO)"),
                y=alt.Y("casos:Q", title="Casos"),
                tooltip=["SEMANA_ISO","casos"]
            )
            .properties(width="container", height=280, title=titulo)
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.subheader(titulo)
        st.bar_chart(agg.set_index("SEMANA_ISO")["casos"])

# ==============================
# Geocache + geocodificação
# ==============================
GEOCACHE_PATH = DATA_DIR / "cache_geocode.csv"

def _load_geocache() -> pd.DataFrame:
    if GEOCACHE_PATH.exists():
        try:
            df = pd.read_csv(GEOCACHE_PATH)
            if not {"ENDERECO_BR","lat","lon"} <= set(df.columns):
                return pd.DataFrame(columns=["ENDERECO_BR","lat","lon"])
            return df.drop_duplicates("ENDERECO_BR")
        except Exception:
            return pd.DataFrame(columns=["ENDERECO_BR","lat","lon"])
    return pd.DataFrame(columns=["ENDERECO_BR","lat","lon"])

def _save_geocache(df: pd.DataFrame):
    GEOCACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.drop_duplicates("ENDERECO_BR").to_csv(GEOCACHE_PATH, index=False)

@st.cache_data(show_spinner=False)
def _geocode_many(addresses, max_new: int = 100) -> pd.DataFrame:
    if not _HAS_GEOPY:
        return pd.DataFrame(columns=["ENDERECO_BR","lat","lon"])
    geolocator = Nominatim(user_agent="monitora-arbo/1.0 (contato: vigilanciaambientalds7@gmail.com)", timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
    rows = []
    for i, addr in enumerate(addresses):
        if i >= max_new: break
        try:
            loc = geocode(addr)
        except Exception:
            loc = None
        if loc:
            rows.append({"ENDERECO_BR": addr, "lat": loc.latitude, "lon": loc.longitude})
    return pd.DataFrame(rows)

def _ensure_latlon_rows(df_addr: pd.DataFrame, col_addr: str = "ENDERECO_BR") -> pd.DataFrame:
    if df_addr is None or col_addr not in df_addr.columns:
        return pd.DataFrame(columns=["ENDERECO_BR","lat","lon","count"])
    counts = (
        df_addr[col_addr].dropna().astype(str).str.strip()
        .value_counts().rename_axis("ENDERECO_BR").reset_index(name="count")
    )
    cache = _load_geocache()
    merged = counts.merge(cache, on="ENDERECO_BR", how="left")
    missing = merged[merged["lat"].isna()]["ENDERECO_BR"].tolist()
    if missing and _HAS_GEOPY:
        new_geo = _geocode_many(missing, max_new=100)
        if not new_geo.empty:
            cache = pd.concat([cache, new_geo], ignore_index=True).drop_duplicates("ENDERECO_BR", keep="first")
            _save_geocache(cache)
            merged = counts.merge(cache, on="ENDERECO_BR", how="left")
    return merged.dropna(subset=["lat","lon"]).reset_index(drop=True)

# ==============================
# Contorno do DS VII
# ==============================
def drive_share_to_direct(url: str) -> str:
    if not url: return url
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", url)
    if m: return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url)
    if m: return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url

def _fetch_bytes_from_url(url: str, timeout: int = 20) -> bytes:
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content

def kml_to_geojson_bytes_fastkml(kml_bytes: bytes) -> bytes:
    if not _HAS_FASTKML or not _HAS_SHAPELY:
        raise RuntimeError("fastkml/shapely não disponíveis")
    k = _fastkml.KML()
    k.from_string(kml_bytes)
    feats = []
    def _walk(objs):
        for obj in objs:
            geom = getattr(obj, "geometry", None)
            if geom is not None:
                feats.append({
                    "type": "Feature",
                    "properties": {"name": getattr(obj, "name", None), "description": getattr(obj, "description", None)},
                    "geometry": mapping(geom)
                })
            if hasattr(obj, "features"):
                _walk(list(obj.features()))
    _walk(list(k.features()))
    return json.dumps({"type":"FeatureCollection","features":feats}, ensure_ascii=False).encode("utf-8")

def kml_to_geojson_bytes_stdlib(kml_bytes: bytes) -> bytes:
    import xml.etree.ElementTree as ET, re as _re, json as _json
    root = ET.fromstring(kml_bytes)
    m = _re.match(r"\{(.+)\}", root.tag)
    ns = {"k": m.group(1) if m else "http://www.opengis.net/kml/2.2"}
    def text(el): return el.text.strip() if el is not None and el.text else ""
    feats = []
    for pm in root.findall(".//k:Placemark", ns):
        name = text(pm.find("k:name", ns))
        desc = text(pm.find("k:description", ns))
        for poly in pm.findall(".//k:Polygon", ns):
            coords_el = poly.find(".//k:outerBoundaryIs/k:LinearRing/k:coordinates", ns)
            if coords_el is None: continue
            coords_text = text(coords_el)
            ring = []
            for item in _re.split(r"\s+", coords_text.strip()):
                if not item: continue
                parts = item.split(",")
                try:
                    lon = float(parts[0]); lat = float(parts[1])
                    ring.append([lon, lat])
                except Exception:
                    pass
            if ring and ring[0] != ring[-1]: ring.append(ring[0])
            if len(ring) >= 4:
                feats.append({
                    "type":"Feature",
                    "properties":{"name":name or None,"description":desc or None},
                    "geometry":{"type":"Polygon","coordinates":[ring]}
                })
    return _json.dumps({"type":"FeatureCollection","features":feats}, ensure_ascii=False).encode("utf-8")

def bootstrap_ds7_geojson():
    DS7_GEOJSON_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DS7_GEOJSON_PATH.exists():
        st.session_state['ds7_status'] = f"OK: contorno já existe em {DS7_GEOJSON_PATH}"
        return

    if DS7_SOURCE.exists():
        shutil.copy(DS7_SOURCE, DS7_GEOJSON_PATH)
        st.session_state['ds7_status'] = "OK: contorno carregado de assets/ds7.geojson"
        return

    if DS7_REMOTE_URL:
        try:
            url = drive_share_to_direct(DS7_REMOTE_URL)
            raw = _fetch_bytes_from_url(url)
            try:
                json.loads(raw.decode("utf-8"))
                DS7_GEOJSON_PATH.write_bytes(raw)
                st.session_state['ds7_status'] = "OK: contorno baixado (GeoJSON remoto)"
                return
            except Exception:
                pass

            try:
                gj = kml_to_geojson_bytes_stdlib(raw)
                DS7_GEOJSON_PATH.write_bytes(gj)
                st.session_state['ds7_status'] = "OK: contorno baixado (KML remoto convertido)"
                return
            except Exception:
                if _HAS_FASTKML and _HAS_SHAPELY:
                    gj = kml_to_geojson_bytes_fastkml(raw)
                    DS7_GEOJSON_PATH.write_bytes(gj)
                    st.session_state['ds7_status'] = "OK: contorno baixado (KML remoto convertido c/ fastkml)"
                    return

            st.session_state['ds7_status'] = "ERRO: baixei a URL mas não reconheci GeoJSON/KML"
        except Exception as e:
            st.session_state['ds7_status'] = f"ERRO: não consegui baixar a URL ({e})"
            return

    st.session_state['ds7_status'] = "FALTA: sem assets/ds7.geojson e sem DS7_REMOTE_URL"

def salvar_ds7_upload_qualquer(file):
    if file is None: return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    name = file.name.lower()
    if name.endswith(".kml"):
        data = file.getbuffer().tobytes()
        gj_bytes = None
        if _HAS_FASTKML and _HAS_SHAPELY:
            try:
                gj_bytes = kml_to_geojson_bytes_fastkml(data)
            except Exception:
                gj_bytes = None
        if gj_bytes is None:
            gj_bytes = kml_to_geojson_bytes_stdlib(data)
        DS7_GEOJSON_PATH.write_bytes(gj_bytes)
        return str(DS7_GEOJSON_PATH)
    DS7_GEOJSON_PATH.write_bytes(file.getbuffer())
    return str(DS7_GEOJSON_PATH)

def carregar_geojson_filtrado(path: Path, campo=None, valor=None):
    with open(str(path), "r", encoding="utf-8") as f:
        gj = json.load(f)
    if not campo: return gj
    alvo = str(valor).strip().upper() if valor is not None else "VII"
    equivalentes = {alvo, "VII", "7", "DS7"}
    feats = []
    for ft in gj.get("features", []):
        v = ft.get("properties", {}).get(campo)
        if v is None: continue
        s = str(v).strip().upper()
        if s in equivalentes: feats.append(ft)
    if feats: return {"type": "FeatureCollection", "features": feats}
    return gj

def folium_add_ds7(m, geojson_path: Path = DS7_GEOJSON_PATH, campo=None, valor="VII", mascara=True):
    if not geojson_path.exists() or not _HAS_FOLIUM: return
    gj = carregar_geojson_filtrado(geojson_path, campo, valor)
    if mascara and _HAS_SHAPELY:
        geoms = [shape(ft["geometry"]) for ft in gj.get("features", [])]
        if geoms:
            ds = unary_union(geoms).buffer(0)
            world = Polygon([(-180,-90),(-180,90),(180,90),(180,-90)])
            mask = world.difference(ds)
            folium.GeoJson(
                mapping(mask),
                name="Máscara DS7",
                style_function=lambda x: {"fillColor":"#000000","color":"#000000","fillOpacity":0.5,"weight":0},
                control=False
            ).add_to(m)
    folium.GeoJson(
        gj, name="DS7 - contorno",
        style_function=lambda x: {"color":"#d00000","weight":2,"fillColor":"#d00000","fillOpacity":0.05}
    ).add_to(m)

def _geojson_to_polygons_for_pydeck(path: Path, campo=None, valor="VII"):
    if not path.exists(): return []
    gj = carregar_geojson_filtrado(path, campo, valor)
    polys = []
    for ft in gj.get("features", []):
        geom = ft.get("geometry", {})
        t = geom.get("type"); coords = geom.get("coordinates", [])
        if t == "Polygon":
            for ring in coords[:1]:
                polys.append({"polygon":[{"lon":x,"lat":y} for x,y in ring]})
        elif t == "MultiPolygon":
            for poly in coords:
                ring = poly[0]
                polys.append({"polygon":[{"lon":x,"lat":y} for x,y in ring]})
    return polys

# ==============================
# Mapa de pontos (Folium / PyDeck)
# ==============================
def plot_mapa_pontos(df_addr: pd.DataFrame, col_addr: str = "ENDERECO_BR", titulo: str = "Mapa de pontos"):
    pontos = _ensure_latlon_rows(df_addr, col_addr)
    if pontos.empty:
        st.info("Sem pontos geocodificados ainda (ou ENDERECO_BR vazio).")
        return
    c_lat = float(pontos["lat"].mean()); c_lon = float(pontos["lon"].mean()); n = len(pontos)

    if _HAS_FOLIUM:
        try:
            m = folium.Map(location=[c_lat,c_lon], zoom_start=12, tiles="cartodbpositron")
            if DS7_GEOJSON_PATH.exists():
                folium_add_ds7(m, DS7_GEOJSON_PATH, st.session_state.get("ds7_campo"), st.session_state.get("ds7_valor"), mascara=True)
            if n > 1500:
                FastMarkerCluster(pontos[["lat","lon"]].values.tolist()).add_to(m)
            elif n > 300:
                mc = MarkerCluster().add_to(m)
                for _, r in pontos.iterrows():
                    folium.CircleMarker(location=[r["lat"],r["lon"]], radius=4, weight=1, color="#d00000", fill=True, fill_opacity=0.6).add_to(mc)
            else:
                for _, r in pontos.iterrows():
                    folium.CircleMarker(location=[r["lat"],r["lon"]], radius=5, weight=1, color="#d00000", fill=True, fill_opacity=0.7,
                                        popup=folium.Popup(r.get("ENDERECO_BR",""), max_width=300)).add_to(m)
            st.subheader(f"🗺️ {titulo} (total: {n})")
            st_folium(m, width=900, height=560)
            return
        except Exception as e:
            st.warning(f"Folium indisponível, usando PyDeck. Detalhe: {e}")

    st.subheader(f"🗺️ {titulo} (total: {n})")
    pts = pontos.rename(columns={"lon":"longitude","lat":"latitude"})
    layers = [pdk.Layer("ScatterplotLayer", data=pts, get_position='[longitude, latitude]',
                        get_radius=30, pickable=True, stroked=True, filled=True,
                        radiusMinPixels=3, radiusMaxPixels=10, lineWidthMinPixels=1)]
    if DS7_GEOJSON_PATH.exists():
        polys = _geojson_to_polygons_for_pydeck(DS7_GEOJSON_PATH, st.session_state.get("ds7_campo"), st.session_state.get("ds7_valor"))
        if polys:
            layers.append(pdk.Layer("PolygonLayer", data=polys, get_polygon="polygon",
                                    get_fill_color="[255, 0, 0, 30]", get_line_color="[200, 0, 0, 200]",
                                    line_width_min_pixels=2, stroked=True, filled=True))
    view_state = pdk.ViewState(latitude=c_lat, longitude=c_lon, zoom=12)
    st.pydeck_chart(pdk.Deck(initial_view_state=view_state, layers=layers, map_style=None))

# ==============================
# Visualização principal
# ==============================
def exibir_dados(df_ve=None, df_va=None, df_sem_encerramento=None, user_email=None):
    with st.expander("🧭 Máscara/contorno do DS VII (opcional)"):
        up = st.file_uploader("Envie o GeoJSON **ou KML** dos Distritos Sanitários do Recife",
                              type=["geojson","json","kml"], key="up_ds7_geojson")
        campo = st.text_input("Campo para filtrar o DS VII (ex.: DS, NUM_DS, NOME, name)", value="DS")
        valor = st.text_input("Valor do DS VII nesse campo (ex.: VII, 7, Distrito Sanitário VII)", value="VII")
        if up is not None:
            try:
                saved = salvar_ds7_upload_qualquer(up)
                st.success(f"Arquivo salvo/convertido em: {saved}")
            except Exception as e:
                st.error(f"Não consegui preparar o arquivo: {e}")
        st.session_state["ds7_campo"] = campo
        st.session_state["ds7_valor"] = valor
        if not DS7_GEOJSON_PATH.exists():
            st.info("Dica: inclua `assets/ds7.geojson` no repositório ou use a URL RAW (já configurada).")
        if not _HAS_SHAPELY:
            st.caption("Sem shapely → contorno aparece, mas **sem** máscara cinza. (opcional)")

    # =======================
    # VE - últimos 60 dias
    # =======================
    if df_ve is not None and not df_ve.empty:
        st.subheader("🦠 Vigilância Epidemiológica (VE) — Últimos 60 dias")
        st.metric("Total de casos no período", f"{len(df_ve)}")
        st.caption("Amostra dos dados (últimos 60 dias)")
        st.dataframe(formatar_datas_para_str_ddmmaaaa(df_ve), use_container_width=True)
        plot_histograma_semana(df_ve, data_col="DT_SIN_PRI", titulo="VE — Total de casos por Semana Epidemiológica (período mostrado)")
        plot_mapa_pontos(df_ve, col_addr="ENDERECO_BR", titulo="VE — Últimos 60 dias")

    # =======================
    # VA — últimos 15 dias
    # =======================
    if df_va is not None and not df_va.empty:
        st.subheader("🦠 Vigilância Ambiental (VA) — Últimos 15 dias")
        st.metric("Total de casos no período", f"{len(df_va)}")
        st.caption("Amostra dos dados (últimos 15 dias)")
        st.dataframe(formatar_datas_para_str_ddmmaaaa(df_va), use_container_width=True)
        plot_histograma_semana(df_va, data_col="DT_SIN_PRI", titulo="VA — Total de casos por Semana Epidemiológica (período mostrado)")
        plot_mapa_pontos(df_va, col_addr="ENDERECO_BR", titulo="VA — Últimos 15 dias")

    # =======================
    # Casos sem encerramento (Exclusivo para Vigilância Epidemiológica)
    # =======================
    if user_email == EMAIL_VE and df_sem_encerramento is not None and not df_sem_encerramento.empty:
        st.subheader("🦠 Casos sem encerramento (visão atual)")
        st.metric("Total de registros", f"{len(df_sem_encerramento)}")
        st.dataframe(formatar_datas_para_str_ddmmaaaa(df_sem_encerramento), use_container_width=True)

# ==============================
# Login / Logout
# ==============================
def login():
    st.title("🔐 Login - Monitora Arboviroses")
    email = st.text_input("Email", key="login_email")
    password = st.text_input("Senha", type="password", key="login_password")
    if st.button("Entrar"):
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            st.session_state.update({"user": user, "email": email, "login_success": True})
            st.rerun()
        except Exception:
            st.error("Email ou senha inválidos.")
            st.session_state["login_success"] = False

def logout():
    cols = st.columns([5, 1])
    cols[0].markdown(
        f"""
        <div style="display: flex; align-items: center; gap: .5rem;">
            <span style="font-size: 16px;">👤</span>
            <span style="font-size: 16px;">{st.session_state.get("email","Usuário")}</span>
        </div>
        """,
        unsafe_allow_html=True
    )
    if cols[1].button("🔒 Sair"):
        st.session_state.clear()
        st.rerun()

# ==============================
# Auxiliares de UI
# ==============================
def apagar_dados():
    try:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        if 'file_uploader' in st.session_state: del st.session_state['file_uploader']
        st.success("✅ Todos os dados e arquivos enviados foram apagados com sucesso.")
    except Exception as e:
        st.error(f"❌ Erro ao apagar os dados: {e}")

def admin_panel(user_email):
    if user_email != EMAIL_ADMIN: return
    with st.expander("➕ Cadastrar Novo Usuário"):
        st.subheader("👤 Cadastro de Novo Usuário")
        new_email = st.text_input("Novo email", key="new_email_input")
        new_password = st.text_input("Nova senha", type="password", key="new_password_input")
        if st.button("Cadastrar novo usuário"):
            if not new_email or not new_password:
                st.warning("Preencha todos os campos.")
            elif not email_valido(new_email):
                st.warning("Informe um e-mail válido.")
            elif len(new_password) < 6:
                st.warning("A senha deve ter no mínimo 6 caracteres.")
            else:
                try:
                    auth.create_user_with_email_and_password(new_email, new_password)
                    st.success(f"✅ Usuário {new_email} criado com sucesso!")
                    time.sleep(2); st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao criar usuário: {e}")

# ==============================
# Processamento / Exibição
# ==============================
def processamento(user_email):
    bootstrap_ds7_geojson()

    status = st.session_state.get('ds7_status')
    if status:
        (st.success if status.startswith("OK")
         else st.error if status.startswith("ERRO")
         else st.warning)(status)

    st.title("📊 Painel de Dados")
    if pode_editar(user_email):
        if st.button("🗑️ Apagar dados", help="Remove todos os arquivos já salvos"):
            apagar_dados()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    uploaded_files = None
    if not user_email == EMAIL_VA:
        uploaded_files = st.file_uploader("Envie arquivos .xls, .ods, .odf ou .dbf",
                                          type=["xls","ods","odf","dbf"], accept_multiple_files=True)
    else:
        st.info("Você tem acesso apenas para visualização dos dados.")

    if uploaded_files:
        for file in uploaded_files:
            with open(TEMP_DIR / file.name, "wb") as f:
                f.write(file.getbuffer())
        try:
            df_ve, df_va, df_sem_encerramento = processar_arquivos(str(TEMP_DIR))

            df_ve = adicionar_endereco_br(remover_colunas_duplicadas(df_ve))
            df_va = adicionar_endereco_br(remover_colunas_duplicadas(df_va))
            df_sem_encerramento = adicionar_endereco_br(remover_colunas_duplicadas(df_sem_encerramento))

            df_ve = filtrar_por_ultimos_dias(df_ve, "DT_SIN_PRI", 60)
            df_va = filtrar_por_ultimos_dias(df_va, "DT_SIN_PRI", 15)

            if pode_editar(user_email):
                df_ve.to_excel(DATA_DIR / "chico_filtrado_ve.xlsx", index=False, engine='openpyxl')
                df_va.to_excel(DATA_DIR / "chico_filtrado_va.xlsx", index=False, engine='openpyxl')
                df_sem_encerramento.to_excel(DATA_DIR / "casos_sem_encerramento.xlsx", index=False, engine='openpyxl')
                st.success("Arquivos processados e salvos com sucesso!")
            else:
                st.info("Arquivos processados apenas para visualização. Nenhum dado foi salvo.")

            exibir_dados(df_ve, df_va, df_sem_encerramento, user_email=user_email)
        except Exception as e:
            st.error(f"Erro ao processar os arquivos: {e}")

    elif pode_visualizar(user_email):
        try:
            df_ve = pd.read_excel(DATA_DIR / "chico_filtrado_ve.xlsx") if pode_editar(user_email) else None
            df_va = pd.read_excel(DATA_DIR / "chico_filtrado_va.xlsx") if user_email == EMAIL_VA else None
            df_sem_encerramento = pd.read_excel(DATA_DIR / "casos_sem_encerramento.xlsx")

            if df_ve is not None:
                df_ve = adicionar_endereco_br(remover_colunas_duplicadas(df_ve))
                df_ve = filtrar_por_ultimos_dias(df_ve, "DT_SIN_PRI", 60)

            if df_va is not None:
                df_va = adicionar_endereco_br(remover_colunas_duplicadas(df_va))
                df_va = filtrar_por_ultimos_dias(df_va, "DT_SIN_PRI", 15)

            df_sem_encerramento = adicionar_endereco_br(remover_colunas_duplicadas(df_sem_encerramento))

            exibir_dados(df_ve, df_va, df_sem_encerramento, user_email=user_email)
        except FileNotFoundError:
            st.warning("Nenhum dado salvo foi encontrado.")

# ==============================
# Execução principal
# ==============================
if 'user' not in st.session_state or not st.session_state.get('login_success'):
    login(); st.stop()
else:
    logout(); admin_panel(st.session_state['email']); processamento(st.session_state['email'])
