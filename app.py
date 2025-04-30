import streamlit as st
import streamlit.components.v1 as components
from process_data import processar_arquivos
import pandas as pd
import base64
import os
import plotly.express as px


# Definindo diretamente o email do usuário (substitua pelo e-mail desejado)
user_email = "seu_email@exemplo.com"  # Substitua com o e-mail que deseja utilizar

# Função para download estilizado
def download_dataframe(df, filename, label):
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    href = f'''
    <a href="data:file/csv;base64,{b64}" download="{filename}">
        <button style="
            background-color: #4CAF50;
            border: none;
            color: white;
            padding: 10px 24px;
            text-align: center;
            text-decoration: none;
            display: inline-block;
            font-size: 16px;
            border-radius: 12px;
            cursor: pointer;">
            ⬇️ {label}
        </button>
    </a>
    '''
    st.markdown(href, unsafe_allow_html=True)

# Função para tela de processamento
def processamento(user_email):
    st.title("Painel de Dados")

    pasta_dados = "dados_salvos"
    os.makedirs(pasta_dados, exist_ok=True)

    if user_email in ["vigilanciaambientalds7@gmail.com"]:
        #Usuário VA: apenas visualiza dados já processados
        try:
            df_va = pd.read_excel(os.path.join(pasta_dados, "chico_filtrado_va.xlsx"))
        except Exception as e:
            st.error(f"Arquivo de dados não foi gerado pelo administrador.")
            return
    else:
        uploaded_files = st.file_uploader("Envie um ou mais arquivos .xls", type=["xls"], accept_multiple_files=True)

        if uploaded_files:
            pasta_temp = "temp_upload"
            os.makedirs(pasta_temp, exist_ok=True)

            # Salvar todos os arquivos enviados
            for uploaded_file in uploaded_files:
                caminho = os.path.join(pasta_temp, uploaded_file.name)
                with open(caminho, "wb") as f:
                    f.write(uploaded_file.getbuffer())

            try:
                df_ve, df_va, df_casos_sem_encerramento = processar_arquivos(pasta_temp)

                df_ve.to_excel(os.path.join(pasta_dados, "chico_filtrado_ve.xlsx"), index=False, engine='openpyxl')
                df_va.to_excel(os.path.join(pasta_dados, "chico_filtrado_va.xlsx"), index=False, engine='openpyxl')
                df_casos_sem_encerramento.to_excel(os.path.join(pasta_dados, "casos_sem_encerramento.xlsx"), index=False, engine='openpyxl')

                st.success("Arquivos processados e salvos com sucesso!")
            except Exception as e:
                st.error(f"Erro ao processar os arquivos: {e}")
                return
        else:
            st.warning("Por favor, envie os arquivos para processar os dados.")
            return

    # Exibição dos dados
    if user_email == "vigilanciaepidemiologicadsvii@gmail.com":
        st.subheader("🦠 Casos dos últimos 60 dias (VE)")
        st.dataframe(df_ve)
        download_dataframe(df_va, "chico_filtrado_ve.csv", "Download VE")

        if 'OPORTUNIDADE_SINAN' in df_va.columns:
            st.subheader("📈 Oportunidades SINAN - VE")
            fig = px.bar(df_va, x=df_va.columns[0], y='OPORTUNIDADE_SINAN', title="Gráfico de Oportunidades SINAN - VE")
            st.plotly_chart(fig, use_container_width=True)

    elif user_email == "vigilanciaambientalds7@gmail.com":
        st.subheader("🦠 Casos dos Últimos 30 Dias (VA)")
        st.dataframe(df_va)
        download_dataframe(df_va, "chico_filtrado_va.csv", "Download VA")
        if 'OPORTUNIDADE_SINAN' in df_va.columns:
            fig = px.bar(df_va, x=df_va.columns[0], y='OPORTUNIDADE_SINAN', title="Oportunidades SINAN - VA")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.subheader("🦠 Casos dos Últimos 60 Dias")
        st.dataframe(df_ve)
        download_dataframe(df_ve, "chico_filtrado_ve.csv", "Download VE")
        st.subheader("🦠 Casos dos Últimos 30 Dias")
        st.dataframe(df_va)
        download_dataframe(df_va, "chico_filtrado_va.csv", "Download VA")
        st.subheader("🦠 Casos sem encerramento")
        st.dataframe(df_casos_sem_encerramento)
        download_dataframe(df_casos_sem_encerramento, "casos_sem_encerramento.csv", "Casos sem encerramento")

# Função de painel admin (se precisar de um painel de admin)
def admin_panel():
    if st.button("Cadastrar Novo Usuário ➕"):
        st.session_state.show_register = True

    if st.session_state.show_register:
        st.subheader("👤 Cadastro de Novo Usuário")
        new_email = st.text_input("Novo email")
        new_password = st.text_input("Nova senha", type="password")

        if st.button("Cadastrar novo usuário"):
            try:
                auth.create_user_with_email_and_password(new_email, new_password)
                st.success(f"Usuário {new_email} criado com sucesso!")
            except Exception as e:
                st.error(f"Erro ao criar usuário: {e}")

# Chamando a função de processamento com o e-mail diretamente
processamento(user_email)
