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
    # Cria um buffer de bytes na memória
    output = io.BytesIO()
    
    # Usa o ExcelWriter para salvar o dataframe no buffer como um arquivo .xlsx
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Dados')
    
    # Pega os dados do buffer
    excel_data = output.getvalue()
    
    # Codifica os dados em base64
    b64 = base64.b64encode(excel_data).decode()
    
    # Garante que o nome do arquivo de download tenha a extensão .xlsx
    new_filename = f"{os.path.splitext(filename)[0]}.xlsx"
    
    # Cria o link de download com o MIME type correto para .xlsx
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
        # Apaga diretórios com dados processados e arquivos importados
        shutil.rmtree("dados_salvos", ignore_errors=True)
        shutil.rmtree("temp_upload", ignore_errors=True)

        # Recria as pastas vazias
        os.makedirs("dados_salvos", exist_ok=True)
        os.makedirs("temp_upload", exist_ok=True)

        # Limpa o estado de arquivos enviados da sessão (se existir)
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

    # Upload habilitado apenas para usuários com permissão
    uploaded_files = None
    if not user_email == EMAIL_VA:
        uploaded_files = st.file_uploader("📂 Envie arquivos .xls, .ods, .odf ou .dbf", type=["xls", "ods", "odf", "dbf"], accept_multiple_files=True)
    else:
        st.info("Você tem acesso apenas para visualização dos dados.")

    if uploaded_files:
        for file in uploaded_files:
            with open(os.path.join("temp_upload", file.name), "wb") as f:
                f.write(file.getbuffer())

        try:
            df_ve, df_va, df_sem_encerramento = processar_arquivos("temp_upload")

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
            exibir_dados(df_ve, df_va, df_sem_encerramento)
        except FileNotFoundError:
            st.warning("Nenhum dado salvo foi encontrado.")

# --- UI: Exibição de Dados ---
def exibir_dados(df_ve=None, df_va=None, df_sem_encerramento=None):
    if df_ve is not None:
        st.subheader("🦠 Casos dos Últimos 60 Dias (VE)")
        st.dataframe(df_ve)
        download_dataframe(df_ve, "chico_filtrado_ve.ods", "Download VE")

        st.subheader("📈 Gráfico - Casos VE por Semana Epidemiológica")
        plotar_casos_por_semana(df_ve, coluna_data='DT_NOTIFIC')

    if df_va is not None:
        st.subheader("🦠 Casos dos Últimos 30 Dias (VA)")
        st.dataframe(df_va)
        download_dataframe(df_va, "chico_filtrado_va.ods", "Download VA")

        st.subheader("📈 Gráfico - Casos VA por Semana Epidemiológica")
        plotar_casos_por_semana(df_va, coluna_data='DT_NOTIFIC')

    if df_sem_encerramento is not None:
        st.subheader("🦠 Casos sem encerramento")
        st.dataframe(df_sem_encerramento)
        download_dataframe(df_sem_encerramento, "casos_sem_encerramento.ods", "Casos sem encerramento")

    if df_sem_encerramento is not None:
        st.subheader("📊 Gráfico Geral - Casos por Semana Epidemiológica")
        # Tenta usar diretamente a coluna SEMANA_EPIDEMIOLOGICA, se existir
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
