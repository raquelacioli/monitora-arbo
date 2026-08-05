# process_data.py
import os
import pandas as pd
from datetime import datetime
import unicodedata

def remover_acentos(texto):
    if not isinstance(texto, str):
        return texto
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def processar_arquivos(pasta):
    arquivos_planilhas = [
        os.path.join(pasta, f) for f in os.listdir(pasta) 
        if f.lower().endswith((".xls", ".xlsx", ".ods", ".odf", ".dbf"))
    ]

    if not arquivos_planilhas:
        raise ValueError("Nenhum arquivo .xls, .xlsx, .ods, .odf ou .dbf encontrado na pasta.")

    dfs = []
    erros_detalhados = []

    for caminho in arquivos_planilhas:
        nome_arq = os.path.basename(caminho)
        try:
            extensao = os.path.splitext(caminho)[1].lower()

            if extensao == '.xls':
                df = pd.read_excel(caminho)
            elif extensao in ['.ods', '.odf']:
                try:
                    df = pd.read_excel(caminho, engine='odf')
                except Exception:
                    df = pd.read_excel(caminho)
            elif extensao == '.xlsx':
                df = pd.read_excel(caminho, engine='openpyxl')
            elif extensao == '.dbf':
                from simpledbf import Dbf5
                dbf = Dbf5(caminho, codec='latin1')
                df = dbf.to_dataframe()
            else:
                continue

            # Normalização de nomes de colunas (Caixa alta e remove vírgula do TabWin)
            df.columns = df.columns.astype(str).str.strip().str.upper().str.split(',').str[0]

            columns_to_select = [
                'NU_NOTIFIC', 'DT_NOTIFIC', 'NU_ANO', 'SEM_NOT', 'ID_UNIDADE', 'DT_SIN_PRI', 'NM_PACIENT', 
                'DT_NASC', 'NU_IDADE_N', 'CS_SEXO', 'CS_GESTANT', 'CS_RACA', 'CS_ESCOL_N', 
                'NM_BAIRRO', 'NM_LOGRADO', 'NU_NUMERO', 'NM_COMPLEM', 'FEBRE', 'MIALGIA', 'CEFALEIA', 
                'EXANTEMA', 'VOMITO', 'NAUSEA', 'DOR_COSTAS', 'CONJUNTVIT', 'ARTRITE', 'ARTRALGIA', 
                'PETEQUIA_N', 'LEUCOPENIA', 'LACO', 'DOR_RETRO', 'DIABETES', 'HEMATOLOG', 'HEPATOPAT', 
                'RENAL', 'HIPERTENSA', 'ACIDO_PEPT', 'AUTO_IMUNE', 'CLASSI_FIN', 'CRITERIO', 'EVOLUCAO', 
                'DT_ENCERRA', 'DT_DIGITA', 'CS_FLXRET'
            ]

            # Cria as colunas que não existirem no arquivo como vazias
            for col in columns_to_select:
                if col not in df.columns:
                    df[col] = ''

            df = df[columns_to_select]
            dfs.append(df)

        except Exception as e:
            erros_detalhados.append(f"[{nome_arq}]: {str(e)}")
            continue

    if not dfs:
        detalhes = " | ".join(erros_detalhados) if erros_detalhados else "Os arquivos estavam vazios ou incompatíveis."
        raise ValueError(f"Falha ao ler arquivos. {detalhes}")

    df = pd.concat(dfs, ignore_index=True)

    # Mapeamentos de códigos do SINAN
    criterio_mapping = {1: 'Laboratório', 2: 'Clínico Epidemiológico', 3: 'Em investigação', 0: 'Em branco'}
    raca_mapping = {1: 'Branca', 2: 'Preta', 3: 'Amarela', 4: 'Parda', 5: 'Indígena', 9: 'Ignorado'}
    evolucao_mapping = {1: 'Cura', 2: 'Óbito', 3: 'Óbito por outra causa', 4: 'Óbito em investigação', 9: 'Ignorado'}

    if 'CRITERIO' in df.columns:
        df['CRITERIO'] = df['CRITERIO'].map(criterio_mapping).fillna(df['CRITERIO'])
    if 'CS_RACA' in df.columns:
        df['CS_RACA'] = df['CS_RACA'].map(raca_mapping).fillna(df['CS_RACA'])
    if 'EVOLUCAO' in df.columns:
        df['EVOLUCAO'] = df['EVOLUCAO'].map(evolucao_mapping).fillna(df['EVOLUCAO'])

    if 'NU_IDADE_N' in df.columns:
        df['NU_IDADE_N'] = pd.to_numeric(df['NU_IDADE_N'], errors='coerce')
        df.loc[df['NU_IDADE_N'] >= 4000, 'NU_IDADE_N'] = df['NU_IDADE_N'] - 4000

    # Filtro flexível por bairros da DS VII (ignora acentos)
    bairros_dsvii = [
        "CORREGO DO JENIPAPO", "NOVA DESCOBERTA", "PASSARINHO", "MACAXEIRA", "VASCO DA GAMA",
        "GUABIRABA", "MORRO DA CONCEICAO", "BREJO DE BEBERIBE", "BREJO DA GUABIRABA", "MANGABEIRA", 
        "BOLA NA REDE", "ALTO JOSE DO PINHO", "ALTO JOSE BONIFACIO"
    ]

    if 'NM_BAIRRO' in df.columns and not df['NM_BAIRRO'].dropna().empty:
        df['NM_BAIRRO_CLEAN'] = df['NM_BAIRRO'].astype(str).apply(remover_acentos).str.upper().str.strip()
        df_filtrado = df[df['NM_BAIRRO_CLEAN'].isin(bairros_dsvii)].copy()
        if not df_filtrado.empty:
            df = df_filtrado
        df.drop(columns=['NM_BAIRRO_CLEAN'], errors='ignore', inplace=True)

    # Filtros por datas de sintomas
    data_atual = pd.to_datetime(datetime.today())
    dt_sin_pri_conv = pd.to_datetime(df['DT_SIN_PRI'], errors='coerce', dayfirst=True)

    df_ve = df[dt_sin_pri_conv >= (data_atual - pd.Timedelta(days=60))].copy()
    if df_ve.empty:
        df_ve = df.copy() # Fallback para não zerar a tela se a data for mais antiga

    df_va = df[dt_sin_pri_conv >= (data_atual - pd.Timedelta(days=15))].copy()
    if df_va.empty:
        df_va = df.copy()

    casos_sem_encerramento = df[df['DT_ENCERRA'].isna() | (df['DT_ENCERRA'].astype(str).str.strip() == "")].copy()

    return df_ve, df_va, casos_sem_encerramento
