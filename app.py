import streamlit as st
import pandas as pd
import pyrebase
import base64
import io
import os
import shutil
import re
import time
from process_data import processar_arquivos
from utils import plotar_casos_por_semana

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

# =========================
# Helpers de dados
# =========================
def remover_colunas_duplicadas(df: pd.DataFrame) -> pd.DataFrame:
    """Remove nomes de colunas EXATAMENTE duplicados (mantém a 1ª ocorrência)."""
    if df is None or not isinstance(df, pd.DataFrame):
        return df
    return df.loc[:, ~df.columns.duplicated(keep='first')].copy()

def pick_nao_vazio(df: pd.DataFrame, prefer: str, fallback: str) -> pd.Series:
    """
    Retorna, linha a linha, o valor da 'prefer' quando não vazia/None/'None'/'NaN';
    caso contrário usa 'fallback'. Se nenhuma existir, devolve vazio.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.Series([])

    pref = df[prefer] if prefer in df.columns else None
    fb   = df[fallback] if fallback in df.columns else None

    if pref is None and fb is None:
        return pd.Series([""] * len(df), index=df.index)

    if pref is None:
        return fb.fillna("").astype(str)

    if fb is None:
        return pref.fillna("").astype(str)

    pref_s = pref.fillna("").astype(str).str.strip()
    fb_s   = fb.fillna("").astype(str).str.strip()

    # trata strings "none", "nan", etc., como vazias
    invalid = {"none", "nan", "nat", "null", "noneType"}
    pref_s = pref_s.where(~pref_s.str.lower().isin(invalid) & (pref_s != ""), "")
    fb_s   = fb_s.where(~fb_s.str.lower().isin(invalid) & (fb_s != ""), "")

    # usa prefer quando não vazia, senão fallback
    out = pref_s.where(pref_s != "", fb_s)
    return out.fillna("")

def adicionar_endereco_br(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cria ENDERECO_BR = 'Brasil, Pernambuco, Recife, NM_BAIRRO, NM_LOGRADO(.1|fallback), NU_NUMERO(.1|fallback)'
    """
    if df is None or not isinstance(df, pd.DataFrame):
        return df

    bairro = df["NM_BAIRRO"] if "NM_BAIRRO" in df.columns else pd.Series([""] * len(df), index=df.index)
    logr   = pick_nao_vazio(df, "NM_LOGRADO.1", "NM_LOGRADO")
    num    = pick_nao_vazio(df, "NU_NUMERO.1", "NU_NUMERO")

    df["ENDERECO_BR"] = (
        "Brasil, Pernambuco, Recife, "
        + bairro.fillna("").astype(str).str.strip()
        + ", "
        + logr.fillna("").astype(str).str.strip()
        + ", "
        + num.fillna("").astype(str).str.strip()
    )

    # Limpezas de vírgulas e espaços sobrando
    df["ENDERECO_BR"] = (
        df["ENDERECO_BR"]
        .str.replace(r"\s+,", ",", regex=True)
        .str.replace(r",\s*,", ", ", regex=True)
        .str.replace(r"(, )+$", "", regex=True)
        .str.replace(r",\s*,", ", ", regex=True)
    )
    return df

def filtrar_por_ultimos_dias(df: pd.DataFrame, coluna_data: str, dias: int) -> pd.DataFrame:
    """Mantém linhas cuja data (coluna_data) esteja nos últimos 'dias' (inclusive)."""
    if df is None or coluna_data not in df.columns:
        return df
    datas = pd.to_datetime(df[coluna_data], errors="coerce", dayfirst=True)
    limite = pd.Timestamp.today().normalize() - pd.Timedelta(days=dias)
    return df.loc[datas >= limite].copy()

def formatar_datas_para_str_ddmmaaaa(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converte para string dd/mm/aaaa as colunas de data (dtype datetime OU nomes que indicam data).
    Não altera o df de origem para cálculos; use em cópias antes de exibir/baixar.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        return df

    df = df.copy()
    padroes_nome = re.compile(r"(^(DT|DATA)_|_DT$|DATA|Data|data)")
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]) or padroes_nome.search(col):
            s = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
            df[col] = s.dt.strftime("%d/%m/%Y")
    return df

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
def download_dataframe(df, filename, label):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Dados')
    excel_data = output.getvalue()
    b64 = base64.b64encode(excel_data).decode()
    new_filename = f"{os.path.splitext(filename)[0]}.xlsx"
    button_html = f"""
    <a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{new_filename}">
        <button style="
            background-color: #4CAF50;
            border: none;
            color: white;
            padding: 10px 24px;
            text-align: center;
            font-size: 16px;
            border-radius: 12px;
            cursor: pointer;">
            ⬇️ {label}
        </button>
    </a>
    """
    st.markdown(button_html, unsafe_allow_html=True)

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

            # 1) Remover nomes de colunas EXATAMENTE duplicados
            df_ve = remover_colunas_duplicadas(df_ve)
            df_va = remover_colunas_duplicadas(df_va)
            df_sem_encerramento = remover_colunas_duplicadas(df_sem_encerramento)

            # 2) Criar ENDERECO_BR (preferindo *.1 quando não vazio; senão fallback)
            df_ve = adicionar_endereco_br(df_ve)
            df_va = adicionar_endereco_br(df_va)
            df_sem_encerramento = adicionar_endereco_br(df_sem_encerramento)

            # 3) Filtrar VA para os últimos 15 dias
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

            # Remover duplicadas exatas após carregar
            df_ve = remover_colunas_duplicadas(df_ve) if df_ve is not None else None
            df_sem_encerramento = remover_colunas_duplicadas(df_sem_encerramento)
            if df_va is not None:
                df_va = remover_colunas_duplicadas(df_va)

            # Garantir ENDERECO_BR
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
    if df_ve is not None:
        st.subheader("🦠 Casos dos Últimos 60 Dias (VE)")
        df_ve_show = formatar_datas_para_str_ddmmaaaa(df_ve)  # datas dd/mm/aaaa
        st.dataframe(df_ve_show)
        download_dataframe(df_ve_show, "chico_filtrado_ve.ods", "Download VE")

        st.subheader("📈 Gráfico - Casos VE por Semana Epidemiológica")
        plotar_casos_por_semana(df_ve, coluna_data='DT_NOTIFIC')  # usa DF original (datas reais)

    if df_va is not None:
        st.subheader("🦠 Casos dos Últimos 15 Dias (VA)")
        df_va_show = formatar_datas_para_str_ddmmaaaa(df_va)  # datas dd/mm/aaaa
        st.dataframe(df_va_show)
        download_dataframe(df_va_show, "chico_filtrado_va.ods", "Download VA")

        st.subheader("📈 Gráfico - Casos VA por Semana Epidemiológica")
        plotar_casos_por_semana(df_va, coluna_data='DT_NOTIFIC')

    if df_sem_encerramento is not None:
        st.subheader("🦠 Casos sem encerramento")
        df_se_show = formatar_datas_para_str_ddmmaaaa(df_sem_encerramento)  # datas dd/mm/aaaa
        st.dataframe(df_se_show)
        download_dataframe(df_se_show, "casos_sem_encerramento.ods", "Casos sem encerramento")

    if df_sem_encerramento is not None:
        st.subheader("📊 Gráfico Geral - Casos por Semana Epidemiológica")
        if 'SEMANA_EPIDEMIOLOGICA' in df_sem_encerramento.columns:
            plotar_casos_por_semana(df_sem_encerramento, coluna_semana='SEMANA_EPIDEMIOLOGICA')
        else:
            plotar_casos_por_semana(df_sem_encerramento, coluna_data='DT_NOTIFIC')

# --- Execução principal ---
if 'user' not in st.session_state or not st.session_state.get('login_success'):
    login()
    st.stop()
else:
    logout()
    admin_panel(st.session_state['email'])
    processamento(st.session_state['email'])
