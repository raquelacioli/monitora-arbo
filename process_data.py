# process_data.py
import os
import pandas as pd
from datetime import datetime

def processar_arquivos(pasta):
    # 1. Localizar todos os arquivos compatíveis na pasta
    arquivos_planilhas = [
        os.path.join(pasta, f) for f in os.listdir(pasta) 
        if f.lower().endswith((".xls", ".xlsx", ".ods", ".odf", ".dbf"))
    ]

    if not arquivos_planilhas:
        raise ValueError("Nenhum arquivo .xls, .xlsx, .ods, .odf ou .dbf encontrado na pasta.")

    dfs = []
    erros_detalhados = []

    # 2. Iterar sobre cada arquivo e aplicar a leitura
    for caminho in arquivos_planilhas:
        nome_arq = os.path.basename(caminho)
        print(f"Lendo: {nome_arq}")
        try:
            extensao = os.path.splitext(caminho)[1].lower()

            if extensao == '.xls':
                df = pd.read_excel(caminho)
            elif extensao in ['.ods', '.odf']:
                # Tenta primeiro com odf, depois com leitor padrão
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

            # 3. Normalização de colunas (caixa alta e sem espaços externos)
            df.columns = df.columns.astype(str).str.strip().str.upper().str.split(',').str[0]

            # Listagem de colunas desejadas do SINAN
            columns_to_select = [
                'NU_NOTIFIC', 'DT_NOTIFIC', 'NU_ANO', 'SEM_NOT', 'ID_UNIDADE', 'DT_SIN_PRI', 'NM_PACIENT', 
                'DT_NASC', 'NU_IDADE_N', 'CS_SEXO', 'CS_GESTANT', 'CS_RACA', 'CS_ESCOL_N', 
                'NM_BAIRRO', 'NM_LOGRADO', 'NU_NUMERO', 'NM_COMPLEM', 'FEBRE', 'MIALGIA', 'CEFALEIA', 
                'EXANTEMA', 'VOMITO', 'NAUSEA', 'DOR_COSTAS', 'CONJUNTVIT', 'ARTRITE', 'ARTRALGIA', 
                'PETEQUIA_N', 'LEUCOPENIA', 'LACO', 'DOR_RETRO', 'DIABETES', 'HEMATOLOG', 'HEPATOPAT', 
                'RENAL', 'HIPERTENSA', 'ACIDO_PEPT', 'AUTO_IMUNE', 'CLASSI_FIN', 'CRITERIO', 'EVOLUCAO', 
                'DT_ENCERRA', 'DT_DIGITA', 'CS_FLXRET'
            ]

            # Adiciona colunas ausentes como vazias para não quebrar a seleção
            for col in columns_to_select:
                if col not in df.columns:
                    df[col] = ''

            # Seleciona apenas as colunas desejadas mantendo a estrutura esperada
            df = df[columns_to_select]
            dfs.append(df)

        except Exception as e:
            msg_erro = f"Erro em [{nome_arq}]: {str(e)}"
            print(msg_erro)
            erros_detalhados.append(msg_erro)
            continue

    if not dfs:
        detalhes = " | ".join(erros_detalhados)
        raise ValueError(f"Nenhum arquivo pôde ser processado com sucesso. Detalhes: {detalhes}")

    # 4. Concatenar todos os DataFrames
    df = pd.concat(dfs, ignore_index=True)

    # 5. Mapear os códigos para valores legíveis
    criterio_mapping = {1: 'Laboratório', 2: 'Clínico Epidemiológico', 3: 'Em investigação', 0: 'Em branco'}
    raca_mapping = {1: 'Branca', 2: 'Preta', 3: 'Amarela', 4: 'Parda', 5: 'Indígena', 9: 'Ignorado'}
    evolucao_mapping = {1: 'Cura', 2: 'Óbito', 3: 'Óbito por outra causa', 4: 'Óbito em investigação', 9: 'Ignorado'}

    if 'CRITERIO' in df.columns:
        df['CRITERIO'] = df['CRITERIO'].map(criterio_mapping).fillna(df['CRITERIO'])
    if 'CS_RACA' in df.columns:
        df['CS_RACA'] = df['CS_RACA'].map(raca_mapping).fillna(df['CS_RACA'])
    if 'EVOLUCAO' in df.columns:
        df['EVOLUCAO'] = df['EVOLUCAO'].map(evolucao_mapping).fillna(df['EVOLUCAO'])

    # Ajuste na idade SINAN
    if 'NU_IDADE_N' in df.columns:
        df['NU_IDADE_N'] = pd.to_numeric(df['NU_IDADE_N'], errors='coerce')
        df.loc[df['NU_IDADE_N'] >= 4000, 'NU_IDADE_N'] = df['NU_IDADE_N'] - 4000

    # Oportunidade SINAN
    df['DT_DIGITA_CONV'] = pd.to_datetime(df['DT_DIGITA'], errors='coerce', dayfirst=True)
    df['DT_NOTIFIC_CONV'] = pd.to_datetime(df['DT_NOTIFIC'], errors='coerce', dayfirst=True)
    df['OPORTUNIDADE_SINAN'] = (df['DT_DIGITA_CONV'] - df['DT_NOTIFIC_CONV']).dt.days

    # Semana Epidemiológica
    if 'SEM_NOT' in df.columns:
        df["SEMANA_EPIDEMIOLOGICA"] = df["SEM_NOT"].astype(str).str[-2:]

    # 6. Filtrar por bairros da DS VII (se houver a coluna NM_BAIRRO preenchida)
    bairros_dsvii = [
        "CORREGO DO JENIPAPO", "NOVA DESCOBERTA", "PASSARINHO", "MACAXEIRA", "VASCO DA GAMA",
        "GUABIRABA", "MORRO DA CONCEICAO", "BREJO DE BEBERIBE", "BREJO DA GUABIRABA", "MANGABEIRA", 
        "BOLA NA REDE", "ALTO JOSÉ DO PINHO", "ALTO JOSÉ BONIFÁCIO", "ALTO JOSE DO PINHO", "ALTO JOSE BONIFACIO"
    ]

    if 'NM_BAIRRO' in df.columns:
        df_filtrado_bairro = df[df["NM_BAIRRO"].astype(str).str.upper().isin(bairros_dsvii)].copy()
        if not df_filtrado_bairro.empty:
            df = df_filtrado_bairro

    # 7. Filtros por data de sintomas (DT_SIN_PRI)
    data_atual = pd.to_datetime(datetime.today())
    dt_sin_pri_conv = pd.to_datetime(df['DT_SIN_PRI'], errors='coerce', dayfirst=True)

    df_ve = df[dt_sin_pri_conv >= (data_atual - pd.Timedelta(days=60))].copy()
    df_va = df[dt_sin_pri_conv >= (data_atual - pd.Timedelta(days=15))].copy()

    # Casos sem encerramento
    casos_sem_encerramento = df[df['DT_ENCERRA'].isna() | (df['DT_ENCERRA'].astype(str).str.strip() == "")].copy()

    # Limpeza de colunas auxiliares
    df_ve.drop(columns=['DT_DIGITA_CONV', 'DT_NOTIFIC_CONV'], errors='ignore', inplace=True)
    df_va.drop(columns=['DT_DIGITA_CONV', 'DT_NOTIFIC_CONV'], errors='ignore', inplace=True)
    casos_sem_encerramento.drop(columns=['DT_DIGITA_CONV', 'DT_NOTIFIC_CONV'], errors='ignore', inplace=True)

    return df_ve, df_va, casos_sem_encerramento
