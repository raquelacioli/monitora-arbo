import plotly.express as px
import streamlit as st
import pandas as pd
def plotar_casos_por_semana(df, coluna_data=None, coluna_semana=None):
    if coluna_semana and coluna_semana in df.columns:
        df_grouped = df.groupby(coluna_semana).size().reset_index(name='Total de Casos')
        df_grouped = df_grouped.sort_values(by=coluna_semana)
        fig = px.bar(df_grouped,
                     x=coluna_semana,
                     y='Total de Casos',
                     labels={coluna_semana: 'Semana Epidemiológica'},
                     title='Casos por Semana Epidemiológica')
        st.plotly_chart(fig, use_container_width=True)

    elif coluna_data and coluna_data in df.columns:
        df['SEMANA_EPIDEMIOLOGICA'] = pd.to_datetime(df[coluna_data], errors='coerce').dt.isocalendar().week
        df_grouped = df.groupby('SEMANA_EPIDEMIOLOGICA').size().reset_index(name='Total de Casos')
        df_grouped = df_grouped.sort_values(by='SEMANA_EPIDEMIOLOGICA')
        fig = px.bar(df_grouped,
                     x='SEMANA_EPIDEMIOLOGICA',
                     y='Total de Casos',
                     labels={'SEMANA_EPIDEMIOLOGICA': 'Semana Epidemiológica'},
                     title='Casos por Semana Epidemiológica')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Coluna de semana ou data inválida para o gráfico.")
