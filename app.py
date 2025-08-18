import streamlit as st
import pandas as pd
import pyrebase
import os
import shutil
import re
import time
import json
import pydeck as pdk  # Fallback do mapa

from process_data import processar_arquivos
from utils import plotar_casos_por_semana  # continua disponível

# --- Configuração do Firebase ---
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

# --- Regras de permissão ---
def pode_visualizar(email):
    return email in [EMAIL_VA, EMAIL_VE]

def pode_editar(email):
    return email == EMAIL_VE

# --- Validação ---
def email_valido(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

# ============== IMPORTS OPCIONAIS (Geopy/Folium/Shapely/fastkml/Altair) ==============
_HAS_GEOPY = False
_HAS_FOLIUM = False
_HAS_SHAPELY = False
_HAS_FASTKML = False
_HAS_ALTAIR = False
_GEOPY_IMPORT_ERROR = None
_FOLIUM_IMPORT_ERROR = None
_SHAPELY_IMPORT_ERROR = None
_FASTKML_IMPORT_ERROR = None
_ALTAIR_IMPORT_ERROR = None

try:
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
    _HAS_GEOPY = True
except Exception as e:
    _GEOPY_IMPORT_ERROR = e

try:
    import folium
    from folium.plugins import MarkerCluster, FastMarkerCluster
    from streamlit_folium import st_folium
    _HAS_FOLIUM = True
except Exception as e:
    _FOLIUM_IMPORT_ERROR = e

try:
    from shapely.geometry import shape, Polygon, MultiPolygon, mapping
    from shapely.ops import unary_union
    _HAS_SHAPELY = True
except Exception as e:
    _SHAPELY_IMPORT_ERROR = e

try:
    from fastkml import kml as _fastkml
    _HAS_FASTKML = True
except Exception as e:
    _FASTKML_IMPORT_ERROR = e

try:
    import altair as alt
    _HAS_ALTAIR = True
except Exception as e:
    _ALTAIR_IMPORT_ERROR = e
# ============================================================================

# =========================
# Helpers de dados
# =========================
def remover_colunas_duplicadas(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return df
    return df.loc[:, ~df.columns.duplicated(keep='first')].copy()

def pick_nao_vazio(df: pd.DataFrame, prefer: str, fallback: str) -> pd.Series:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.Series([], dtype=object)
    pref = df[prefer] if prefer in df.columns else None
    fb   = df[fallback] if fallback in df.columns else None
    if pref is None and fb is None:
        return pd.Series([""] * len(df), index=df.index, dtype=object)
    if pref is None:
        return fb.fillna("").astype(str)
    if fb is None:
        return pref.fillna("").astype(str)
    pref_s = pref.fillna("").astype(str).str.strip()
    fb_s   = fb.fillna("").astype(str).str.strip()
    invalid = {"none", "nan", "nat", "null", "nonetype"}
    pref_s = pref_s.where(~pref_s.str.lower().isin(invalid) & (pref_s != ""), "")
    fb_s   = fb_s.where(~fb_s.str.lower().isin(invalid) & (fb_s != ""), "")
    return pref_s.where(pref_s != "", fb_s).fillna("")

def adicionar_endereco_br(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return df
    bairro = df["NM_BAIRRO"] if "NM_BAIRRO" in df.columns else pd.Series([""] * len(df), index=df.index)
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
    if df is None or coluna_data not in df.columns:
        return df
    datas = pd.to_datetime(df[coluna_data], errors="coerce", dayfirst=True)
    limite = pd.Timestamp.today().normalize() - pd.Timedelta(days=dias)
    return df.loc[datas >= limite].copy()

def formatar_datas_para_str_ddmmaaaa(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return df
    df = df.copy()
    padroes_nome = re.compile(r"(^(DT|DATA)_|_DT$|DATA|Data|data)")
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]) or padroes_nome.search(col):
            s = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
            df[col] = s.dt.strftime("%d/%m/%Y")
    return df

# =========================
# Epidemiologia (ano corrente: semanas ISO)
# =========================
def add_epi_cols(df: pd.DataFrame, data_col: str = "DT_NOTIFIC") -> pd.DataFrame:
    """Adiciona ANO_ISO, SEMANA_ISO e MES a partir da coluna de data."""
    if df is None or data_col not in df.columns:
        return df
    df = df.copy()
    datas = pd.to_datetime(df[data_col], errors="coerce", dayfirst=True)
    iso = datas.dt.isocalendar()
    df["ANO_ISO"] = iso["year"].astype("Int64")
    df["SEMANA_ISO"] = iso["week"].astype("Int64")
    df["MES"] = datas.dt.month.astype("Int64")
    return df

def serie_semanal_do_ano(df: pd.DataFrame, ano: int, data_col: str = "DT_NOTIFIC") -> pd.DataFrame:
    """Retorna DataFrame com colunas: SEMANA_ISO (1..53) e casos (contagem), só do ano desejado."""
    if df is None:
        return pd.DataFrame(columns=["SEMANA_ISO","casos"])
    tmp = add_epi_cols(df, data_col)
    tmp = tmp[tmp["ANO_ISO"] == ano]
    if tmp.empty:
        return pd.DataFrame(columns=["SEMANA_ISO","casos"])
    agg = tmp.groupby("SEMANA_ISO", dropna=True).size().rename("casos").reset_index()
    # Garante todas as semanas 1..53 presentes (preenche zero)
    full = pd.DataFrame({"SEMANA_ISO": list(range(1, 54))})
    out = full.merge(agg, on="SEMANA_ISO", how="left").fillna({"casos": 0})
    out["casos"] = out["casos"].astype(int)
    return out

def plot_linha_semanal(df: pd.DataFrame, titulo: str):
    """Plota linha (Altair se disponível; senão, st.line_chart)."""
    if df.empty:
        st.info("Sem dados para o ano selecionado.")
        return
    if _HAS_ALTAIR:
        chart = (
            alt.Chart(df)
            .mark_line(point=True)
            .encode(
                x=alt.X("SEMANA_ISO:Q", title="Semana Epidemiológica (ISO)"),
                y=alt.Y("casos:Q", title="Casos"),
                tooltip=["SEMANA_ISO","casos"]
            )
            .properties(width="container", height=280, title=titulo)
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.subheader(titulo)
        st.line_chart(df.set_index("SEMANA_ISO")["casos"])

# =========================
# Geocache + geocodificação
# =========================
GEOCACHE_PATH = "dados_salvos/cache_geocode.csv"

def _load_geocache() -> pd.DataFrame:
    if os.path.exists(GEOCACHE_PATH):
        try:
            df = pd.read_csv(GEOCACHE_PATH)
            if not {"ENDERECO_BR","lat","lon"} <= set(df.columns):
                return pd.DataFrame(columns=["ENDERECO_BR","lat","lon"])
            return df.drop_duplicates("ENDERECO_BR")
        except Exception:
            return pd.DataFrame(columns=["ENDERECO_BR","lat","lon"])
    return pd.DataFrame(columns=["ENDERECO_BR","lat","lon"])

def _save_geocache(df: pd.DataFrame):
    os.makedirs(os.path.dirname(GEOCACHE_PATH), exist_ok=True)
    df.drop_duplicates("ENDERECO_BR").to_csv(GEOCACHE_PATH, index=False)

@st.cache_data(show_spinner=False)
def _geocode_many(addresses, max_new: int = 100) -> pd.DataFrame:
    if not _HAS_GEOPY:
        return pd.DataFrame(columns=["ENDERECO_BR","lat","lon"])
    geolocator = Nominatim(user_agent="monitora-arbo/1.0 (contato: vigilanciaambientalds7@gmail.com)", timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
    rows = []
    for i, addr in enumerate(addresses):
        if i >= max_new:
            break
        try:
            loc = geocode(addr)
        except Exception:
            loc = None
        if loc:
            rows.append({"ENDERECO_BR": addr, "lat": loc.latitude, "lon": loc.longitude})
    return pd.DataFrame(rows)

def _ensure_latlon_rows(df_addr: pd.DataFrame, col_addr: str = "ENDERECO_BR") -> pd.DataFrame:
    """Retorna 1 linha por endereço com lat/lon e uma coluna 'count' (quantos casos)."""
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

# =========================
# DS7: upload/contorno/máscara + KML
# =========================
DS7_GEOJSON_PATH = "dados_salvos/ds7.geojson"

def bootstrap_ds7_geojson():
    """Se houver 'ds7.geojson' ao lado do app, copia para 'dados_salvos/ds7.geojson'."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        base_dir = os.getcwd()
    src = os.path.join(base_dir, "ds7.geojson")
    dst_dir = "dados_salvos"
    dst = os.path.join(dst_dir, "ds7.geojson")
    os.makedirs(dst_dir, exist_ok=True)
    if os.path.exists(src) and not os.path.exists(dst):
        shutil.copy(src, dst)

# Conversores KML -> GeoJSON
def kml_to_geojson_bytes_fastkml(kml_bytes: bytes) -> bytes:
    """Usa fastkml+shapely (se instalados)."""
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
    fc = {"type": "FeatureCollection", "features": feats}
    return json.dumps(fc, ensure_ascii=False).encode("utf-8")

def kml_to_geojson_bytes_stdlib(kml_bytes: bytes) -> bytes:
    """Fallback só com stdlib: lê Polygons (anel externo)."""
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
            if coords_el is None:
                continue
            coords_text = text(coords_el)
            ring = []
            for item in _re.split(r"\s+", coords_text.strip()):
                if not item:
                    continue
                parts = item.split(",")
                try:
                    lon = float(parts[0]); lat = float(parts[1])
                    ring.append([lon, lat])
                except Exception:
                    pass
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            if len(ring) >= 4:
                feats.append({
                    "type": "Feature",
                    "properties": {"name": name or None, "description": desc or None},
                    "geometry": {"type": "Polygon", "coordinates": [ring]}
                })
    return _json.dumps({"type":"FeatureCollection","features":feats}, ensure_ascii=False).encode("utf-8")

def salvar_ds7_upload_qualquer(file):
    """Aceita GeoJSON/JSON/KML. Se KML: converte para GeoJSON (tenta fastkml; cai no stdlib)."""
    if file is None:
        return None
    os.makedirs("dados_salvos", exist_ok=True)
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
            # fallback stdlib
            gj_bytes = kml_to_geojson_bytes_stdlib(data)
        with open(DS7_GEOJSON_PATH, "wb") as f:
            f.write(gj_bytes)
        return DS7_GEOJSON_PATH

    # GeoJSON/JSON direto
    with open(DS7_GEOJSON_PATH, "wb") as f:
        f.write(file.getbuffer())
    return DS7_GEOJSON_PATH

def carregar_geojson_filtrado(path, campo=None, valor=None):
    with open(path, "r", encoding="utf-8") as f:
        gj = json.load(f)
    if not campo:
        return gj
    alvo = str(valor).strip().upper() if valor is not None else "VII"
    equivalentes = {alvo, "VII", "7", "DS7"}
    feats = []
    for ft in gj.get("features", []):
        v = ft.get("properties", {}).get(campo)
        if v is None:
            continue
        s = str(v).strip().upper()
        if s in equivalentes:
            feats.append(ft)
    if feats:
        return {"type": "FeatureCollection", "features": feats}
    return gj

def folium_add_ds7(m, geojson_path=DS7_GEOJSON_PATH, campo=None, valor="VII", mascara=True):
    if not os.path.exists(geojson_path) or not _HAS_FOLIUM:
        return
    gj = carregar_geojson_filtrado(geojson_path, campo, valor)
    # Máscara fora do DS
    if mascara and _HAS_SHAPELY:
        geoms = [shape(ft["geometry"]) for ft in gj.get("features", [])]
        if geoms:
            ds = unary_union(geoms).buffer(0)
            world = Polygon([(-180, -90), (-180, 90), (180, 90), (180, -90)])
            mask = world.difference(ds)
            folium.GeoJson(
                mapping(mask),
                name="Máscara DS7",
                style_function=lambda x: {"fillColor": "#000000", "color": "#000000",
                                          "fillOpacity": 0.5, "weight": 0},
                control=False
            ).add_to(m)
    # Contorno/preenchimento leve
    folium.GeoJson(
        gj, name="DS7 - contorno",
        style_function=lambda x: {"color": "#d00000", "weight": 2,
                                  "fillColor": "#d00000", "fillOpacity": 0.05}
    ).add_to(m)

def _geojson_to_polygons_for_pydeck(path, campo=None, valor="VII"):
    if not os.path.exists(path):
        return []
    gj = carregar_geojson_filtrado(path, campo, valor)
    polys = []
    for ft in gj.get("features", []):
        geom = ft.get("geometry", {})
        t = geom.get("type")
        coords = geom.get("coordinates", [])
        if t == "Polygon":
            for ring in coords[:1]:
                polys.append({"polygon": [{"lon": x, "lat": y} for x, y in ring]})
        elif t == "MultiPolygon":
            for poly in coords:
                ring = poly[0]
                polys.append({"polygon": [{"lon": x, "lat": y} for x, y in ring]})
    return polys

# =========================
# Mapa de PONTOS (Folium → fallback PyDeck)
# =========================
def plot_mapa_pontos(df_addr: pd.DataFrame, col_addr: str = "ENDERECO_BR", titulo: str = "Mapa de pontos"):
    """Renderiza um mapa de pontos; DS7 contorno/máscara mantidos."""
    pontos = _ensure_latlon_rows(df_addr, col_addr)
    if pontos.empty:
        st.info("Sem pontos geocodificados ainda (ou ENDERECO_BR vazio).")
        return

    c_lat = float(pontos["lat"].mean())
    c_lon = float(pontos["lon"].mean())
    n = len(pontos)

    # 1) Tenta Folium
    if _HAS_FOLIUM:
        try:
            m = folium.Map(location=[c_lat, c_lon], zoom_start=12, tiles="cartodbpositron")
            # DS7
            if os.path.exists(DS7_GEOJSON_PATH):
                folium_add_ds7(
                    m,
                    geojson_path=DS7_GEOJSON_PATH,
                    campo=st.session_state.get("ds7_campo"),
                    valor=st.session_state.get("ds7_valor"),
                    mascara=True
                )
            # Marcadores (cluster quando muitos pontos)
            if n > 1500:
                data = pontos[["lat","lon"]].values.tolist()
                FastMarkerCluster(data).add_to(m)
            elif n > 300:
                mc = MarkerCluster().add_to(m)
                for _, r in pontos.iterrows():
                    folium.CircleMarker(
                        location=[r["lat"], r["lon"]],
                        radius=4, weight=1, color="#d00000", fill=True, fill_opacity=0.6
                    ).add_to(mc)
            else:
                for _, r in pontos.iterrows():
                    folium.CircleMarker(
                        location=[r["lat"], r["lon"]],
                        radius=5, weight=1, color="#d00000", fill=True, fill_opacity=0.7,
                        popup=folium.Popup(r.get("ENDERECO_BR",""), max_width=300)
                    ).add_to(m)

            st.subheader(f"🗺️ {titulo} (total: {n})")
            st_folium(m, width=900, height=560)
            return
        except Exception as e:
            st.warning(f"Folium indisponível, usando PyDeck. Detalhe: {e}")

    # 2) Fallback: PyDeck
    st.subheader(f"🗺️ {titulo} (total: {n})")
    pts = pontos.rename(columns={"lon":"longitude","lat":"latitude"})
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=pts,
            get_position='[longitude, latitude]',
            get_radius=30, pickable=True, stroked=True, filled=True,
            radiusMinPixels=3, radiusMaxPixels=10,
            lineWidthMinPixels=1
        )
    ]
    # Contorno DS7
    if os.path.exists(DS7_GEOJSON_PATH):
        polys = _geojson_to_polygons_for_pydeck(
            DS7_GEOJSON_PATH,
            campo=st.session_state.get("ds7_campo"),
            valor=st.session_state.get("ds7_valor")
        )
        if polys:
            layers.append(
                pdk.Layer(
                    "PolygonLayer",
                    data=polys,
                    get_polygon="polygon",
                    get_fill_color="[255, 0, 0, 30]",
                    get_line_color="[200, 0, 0, 200]",
                    line_width_min_pixels=2,
                    stroked=True, filled=True
                )
            )
    view_state = pdk.ViewState(latitude=c_lat, longitude=c_lon, zoom=12)
    st.pydeck_chart(pdk.Deck(initial_view_state=view_state, layers=layers, map_style=None))

# =========================
# UI: linha por semana (ano corrente) + mapa por semana
# =========================
def bloco_ano_corrente(df: pd.DataFrame, nome_bloco: str, data_col: str = "DT_NOTIFIC"):
    """Mostra linha semanal do ano corrente e mapa por semana (com filtro opcional por mês)."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return
    ano_ref = pd.Timestamp.today().year  # 'último ano' = ano corrente (ex.: 2025)

    # Prepara colunas epidemiológicas
    base = add_epi_cols(df, data_col)
    base_ano = base[base["ANO_ISO"] == ano_ref].copy()

    st.markdown(f"### 📆 {nome_bloco}: {ano_ref} — Casos por Semana Epidemiológica")

    # Série semanal e linha
    serie = serie_semanal_do_ano(base, ano_ref, data_col)
    plot_linha_semanal(serie, f"Total de casos por Semana Epidemiológica — {ano_ref}")

    # Mapa por semana (filtro de mês opcional)
    if base_ano.empty:
        st.info(f"Sem registros com {data_col} em {ano_ref}.")
        return

    col_m, col_s = st.columns([1, 2])
    with col_m:
        meses_disp = sorted(base_ano["MES"].dropna().unique().tolist())
        meses_label = {1:"Jan",2:"Fev",3:"Mar",4:"Abr",5:"Mai",6:"Jun",7:"Jul",8:"Ago",9:"Set",10:"Out",11:"Nov",12:"Dez"}
        mes_sel = st.selectbox("Filtrar por mês (opcional)", ["Todos"] + [meses_label.get(m, str(m)) for m in meses_disp])
        if mes_sel != "Todos":
            # resolve número do mês
            inv = {v:k for k,v in meses_label.items()}
            mes_num = inv.get(mes_sel, None)
            base_filtro = base_ano[base_ano["MES"] == mes_num].copy()
        else:
            base_filtro = base_ano.copy()

    with col_s:
        sem_disp = sorted(base_filtro["SEMANA_ISO"].dropna().unique().tolist())
        if not sem_disp:
            st.info("Sem semanas para o filtro selecionado.")
            return
        sem_sel = st.slider("Semana Epidemiológica", min_value=int(min(sem_disp)), max_value=int(max(sem_disp)), value=int(max(sem_disp)), step=1)

    # Subconjunto para o mapa daquela semana
    subset_sem = base_filtro[base_filtro["SEMANA_ISO"] == sem_sel]
    if subset_sem.empty:
        st.info("Sem casos para a semana/mês selecionados.")
    else:
        plot_mapa_pontos(subset_sem, col_addr="ENDERECO_BR", titulo=f"Mapa de pontos — Semana {sem_sel} / {ano_ref}")

# --- UI: Login ---
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
    elif st.session_state.get("login_success"):
        st.success(f"Bem-vindo, {st.session_state['email']}!")
        st.stop()

# --- UI: Logout ---
def logout():
    col1, col2 = st.columns([5, 1])
    with col1:
        st.markdown(f"""
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span style="font-size: 16px;">👤</span>
                <span style="font-size: 16px;">{st.session_state.get("email", "Usuário")}</span>
            </div>
        """, unsafe_allow_html=True)
    with col2:
        if st.button("🔒 Sair"):
            st.session_state.clear()
            st.rerun()

# --- Funções auxiliares ---
def apagar_dados():
    try:
        shutil.rmtree("dados_salvos", ignore_errors=True)
        shutil.rmtree("temp_upload", ignore_errors=True)
        os.makedirs("dados_salvos", exist_ok=True)
        os.makedirs("temp_upload", exist_ok=True)
        if 'file_uploader' in st.session_state:
            del st.session_state['file_uploader']
        st.success("✅ Todos os dados e arquivos enviados foram apagados com sucesso.")
    except Exception as e:
        st.error(f"❌ Erro ao apagar os dados: {e}")

# --- UI: Cadastro Admin ---
def admin_panel(user_email):
    if user_email != EMAIL_ADMIN:
        return
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
                    time.sleep(2)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao criar usuário: {e}")

# --- UI: Processamento de Dados ---
def processamento(user_email):
    # Bootstrap do DS7 (copia ds7.geojson local para dados_salvos/ se existir)
    bootstrap_ds7_geojson()

    st.title("📊 Painel de Dados")

    if pode_editar(user_email):
        if st.button("🗑️ Apagar dados", help="Remove todos os arquivos já salvos"):
            apagar_dados()

    os.makedirs("dados_salvos", exist_ok=True)
    os.makedirs("temp_upload", exist_ok=True)

    uploaded_files = None
    if not user_email == EMAIL_VA:
        uploaded_files = st.file_uploader(
            "📂 Envie arquivos .xls, .ods, .odf ou .dbf",
            type=["xls", "ods", "odf", "dbf"],
            accept_multiple_files=True
        )
    else:
        st.info("Você tem acesso apenas para visualização dos dados.")

    if uploaded_files:
        for file in uploaded_files:
            with open(os.path.join("temp_upload", file.name), "wb") as f:
                f.write(file.getbuffer())
        try:
            df_ve, df_va, df_sem_encerramento = processar_arquivos("temp_upload")
            # Limpezas
            df_ve = remover_colunas_duplicadas(df_ve)
            df_va = remover_colunas_duplicadas(df_va)
            df_sem_encerramento = remover_colunas_duplicadas(df_sem_encerramento)
            # ENDERECO_BR
            df_ve = adicionar_endereco_br(df_ve)
            df_va = adicionar_endereco_br(df_va)
            df_sem_encerramento = adicionar_endereco_br(df_sem_encerramento)
            # Filtro VA 15 dias
            df_va = filtrar_por_ultimos_dias(df_va, "DT_NOTIFIC", 15)
            if pode_editar(user_email):
                df_ve.to_excel("dados_salvos/chico_filtrado_ve.xlsx", index=False, engine='openpyxl')
                df_va.to_excel("dados_salvos/chico_filtrado_va.xlsx", index=False, engine='openpyxl')
                df_sem_encerramento.to_excel("dados_salvos/casos_sem_encerramento.xlsx", index=False, engine='openpyxl')
                st.success("Arquivos processados e salvos com sucesso!")
            else:
                st.info("Arquivos processados apenas para visualização. Nenhum dado foi salvo.")
            exibir_dados(df_ve, df_va, df_sem_encerramento)
        except Exception as e:
            st.error(f"Erro ao processar os arquivos: {e}")

    elif pode_visualizar(user_email):
        try:
            df_ve = pd.read_excel("dados_salvos/chico_filtrado_ve.xlsx") if pode_editar(user_email) else None
            df_va = pd.read_excel("dados_salvos/chico_filtrado_va.xlsx") if user_email == EMAIL_VA else None
            df_sem_encerramento = pd.read_excel("dados_salvos/casos_sem_encerramento.xlsx")
            # Limpezas
            df_ve = remover_colunas_duplicadas(df_ve) if df_ve is not None else None
            df_sem_encerramento = remover_colunas_duplicadas(df_sem_encerramento)
            if df_va is not None:
                df_va = remover_colunas_duplicadas(df_va)
            # ENDERECO_BR
            df_ve = adicionar_endereco_br(df_ve) if df_ve is not None else None
            df_sem_encerramento = adicionar_endereco_br(df_sem_encerramento)
            if df_va is not None:
                df_va = adicionar_endereco_br(df_va)
                df_va = filtrar_por_ultimos_dias(df_va, "DT_NOTIFIC", 15)
            exibir_dados(df_ve, df_va, df_sem_encerramento)
        except FileNotFoundError:
            st.warning("Nenhum dado salvo foi encontrado.")

# --- UI: Exibição de Dados ---
def exibir_dados(df_ve=None, df_va=None, df_sem_encerramento=None):
    with st.expander("🧭 Máscara/contorno do DS VII (opcional)"):
        up = st.file_uploader(
            "Envie o GeoJSON **ou KML** dos Distritos Sanitários do Recife",
            type=["geojson", "json", "kml"], key="up_ds7_geojson"
        )
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
        if not os.path.exists(DS7_GEOJSON_PATH):
            st.info("Dica: coloque um 'ds7.geojson' ao lado do app ou envie um arquivo aqui.")
        if not _HAS_SHAPELY:
            st.caption("Sem shapely → contorno aparece, mas **sem** máscara. Instale: `python -m pip install shapely`")

    # Diagnóstico opcional
    with st.expander("🔧 Diagnóstico do ambiente (opcional)", expanded=False):
        import sys, pkgutil
        st.write("Python:", sys.version)
        st.write("Exe:", sys.executable)
        st.write("folium?", pkgutil.find_loader("folium") is not None)
        st.write("streamlit_folium?", pkgutil.find_loader("streamlit_folium") is not None)
        st.write("geopy?", pkgutil.find_loader("geopy") is not None)
        st.write("shapely?", pkgutil.find_loader("shapely") is not None)
        st.write("fastkml?", pkgutil.find_loader("fastkml") is not None)
        st.write("altair?", pkgutil.find_loader("altair") is not None)

    # VE
    if df_ve is not None:
        st.subheader("🦠 Casos dos Últimos 60 Dias (VE)")
        df_ve_show = formatar_datas_para_str_ddmmaaaa(df_ve)
        st.dataframe(df_ve_show, use_container_width=True)

        st.subheader("📈 Casos VE por Semana Epidemiológica (padrão do app)")
        plotar_casos_por_semana(df_ve, coluna_data='DT_NOTIFIC')

        # NOVO: Ano corrente — linha + mapa por semana
        bloco_ano_corrente(df_ve, "VE", data_col="DT_NOTIFIC")

    # VA
    if df_va is not None:
        st.subheader("🦠 Casos dos Últimos 15 Dias (VA)")
        df_va_show = formatar_datas_para_str_ddmmaaaa(df_va)
        st.dataframe(df_va_show, use_container_width=True)

        st.subheader("📈 Casos VA por Semana Epidemiológica (padrão do app)")
        plotar_casos_por_semana(df_va, coluna_data='DT_NOTIFIC')

        # NOVO: Ano corrente — linha + mapa por semana
        bloco_ano_corrente(df_va, "VA", data_col="DT_NOTIFIC")

    # Sem encerramento
    if df_sem_encerramento is not None:
        st.subheader("🦠 Casos sem encerramento")
        df_se_show = formatar_datas_para_str_ddmmaaaa(df_sem_encerramento)
        st.dataframe(df_se_show, use_container_width=True)

        st.subheader("📊 Gráfico Geral - Casos por Semana Epidemiológica (padrão do app)")
        if 'SEMANA_EPIDEMIOLOGICA' in df_sem_encerramento.columns:
            plotar_casos_por_semana(df_sem_encerramento, coluna_semana='SEMANA_EPIDEMIOLOGICA')
        else:
            plotar_casos_por_semana(df_sem_encerramento, coluna_data='DT_NOTIFIC')

        # NOVO: Ano corrente — linha + mapa por semana
        bloco_ano_corrente(df_sem_encerramento, "Casos sem encerramento", data_col="DT_NOTIFIC")

# --- Execução principal ---
if 'user' not in st.session_state or not st.session_state.get('login_success'):
    login()
    st.stop()
else:
    logout()
    admin_panel(st.session_state['email'])
    processamento(st.session_state['email'])
