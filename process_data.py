import pandas as pd
import glob
import os

from datetime import datetime

def processar_arquivos(pasta):
    # 1. Localizar todos os arquivos .xls .ods na pasta 'arquivos/'
    arquivos_planilhas = [os.path.join(pasta, f) for f in os.listdir(pasta) if f.endswith((".xls", ".ods"))]

    if not arquivos_planilhas:
        raise ValueError("Nenhum arquivo .xls ou .ods encontrado na pasta.")

    # 2. Lista para armazenar DataFrames    
    dfs = []

    # 3. Iterar sobre cada arquivo e aplicar o processamento inicial
    for caminho in arquivos_planilhas:
        print(f"Lendo: {caminho}")
        try:
            extensao = os.path.splitext(caminho)[1].lower()

            if extensao == '.xls':
                df = pd.read_excel(caminho, engine='xlrd')
            elif extensao == '.ods':
                try:
                    df = pd.read_excel(caminho, engine='calamine')
                except Exception as e1:
                    print(f'Erro com engine=calamine: {e1}')
                    try:
                        df = pd.read_excel(caminho, engine='odf')
                    except Exception as e2:
                        print(f'Erro com engine=odf: {e2}')
                        return None
            # # 4. Imprimir os nomes das colunas para depuração
            # print("Colunas no dataset:")
            # print(df.columns.tolist())

            # 5. Limpar os nomes das colunas: manter só o nome antes da vírgula
            df.columns = df.columns.str.split(',').str[0]
            print("Colunas encontradas:", df.columns.tolist())

            # 6. Selecionar as colunas relevantes para análise
            columns_to_select = [
                'NU_NOTIFIC', 'DT_NOTIFIC', 'NU_ANO', 'SEM_NOT', 'ID_UNIDADE', 'DT_SIN_PRI', 'NM_PACIENT', 
                'DT_NASC', 'NU_IDADE_N', 'CS_SEXO', 'CS_GESTANT', 'CS_RACA', 'CS_ESCOL_N', 
                'NM_BAIRRO', 'NM_LOGRADO', 'NU_NUMERO', 'NM_COMPLEM', 'FEBRE', 'MIALGIA', 'CEFALEIA', 
                'EXANTEMA', 'VOMITO', 'NAUSEA', 'DOR_COSTAS', 'CONJUNTVIT', 'ARTRITE', 'ARTRALGIA', 
                'PETEQUIA_N', 'LEUCOPENIA', 'LACO', 'DOR_RETRO', 'DIABETES', 'HEMATOLOG', 'HEPATOPAT', 
                'RENAL', 'HIPERTENSA', 'ACIDO_PEPT', 'AUTO_IMUNE', 'CLASSI_FIN', 'CRITERIO', 'EVOLUCAO', 
                'DT_ENCERRA', 'DT_DIGITA', 'CS_FLXRET'
            ]

            df = df[columns_to_select]

            dfs.append(df)

        except Exception as e:
            print(f"Erro ao ler {caminho}: {e}")
            continue

    if not dfs:
        raise ValueError("Nenhum arquivo pôde ser processado com sucesso.")
    
    # 7. Concatenar todos os DataFrames
    df = pd.concat(dfs, ignore_index=True)


    # 8. Criar coluna MAPA para o Dashboard
    df['MAPA'] = df['NM_BAIRRO'] + ', BRASIL, PERNAMBUCO, RECIFE'

    # 9. Mapear os códigos para valores legíveis
    criterio_mapping = {
        1: 'Laboratório', 2: 'Clínico Epidemiológico', 3: 'Em investigação', 0: 'Em branco'
    }
    raca_mapping = {
        1: 'Branca', 2: 'Preta', 3: 'Amarela', 4: 'Parda', 5: 'Indígena', 9: 'Ignorado'
    }
    evolucao_mapping = {
        1: 'Cura', 2: 'Óbito', 3: 'Óbito por outra causa', 4: 'Óbito em investigação', 9: 'Ignorado'
    }

    df['CRITERIO'] = df['CRITERIO'].map(criterio_mapping)
    df['NU_IDADE_N'] = df['NU_IDADE_N'] - 4000
    df['CS_RACA'] = df['CS_RACA'].map(raca_mapping)
    df['EVOLUCAO'] = df['EVOLUCAO'].map(evolucao_mapping)
    df['DT_DIGITA'] = pd.to_datetime(df['DT_DIGITA'], errors='coerce')
    df['DT_NOTIFIC'] = pd.to_datetime(df['DT_NOTIFIC'], errors='coerce')
    df['OPORTUNIDADE_SINAN'] = (df['DT_DIGITA'] - df['DT_NOTIFIC']).dt.days


    # 11. Calcular Semana Epidemiológica
    df["SEMANA_EPIDEMIOLOGICA"] = df["SEM_NOT"].astype(str).str[-2:]

    # 12. Filtrar por bairros da DSVII
    bairros_dsvii = [
        "CORREGO DO JENIPAPO", "NOVA DESCOBERTA", "PASSARINHO", "MACAXEIRA", "VASCO DA GAMA",
        "GUABIRABA", "MORRO DA CONCEICAO", "BREJO DE BEBERIBE", "BREJO DA GUABIRABA", "MANGABEIRA", 
        "BOLA NA REDE", "ALTO JOSÉ DO PINHO", "ALTO JOSÉ BONIFÁCIO", "ALTO JOSE DO PINHO", "ALTO JOSE BONIFACIO"
    ]

    df = df[df["NM_BAIRRO"].str.upper().isin(bairros_dsvii)]

    data_atual = pd.to_datetime(datetime.today())

    df_ve = df[df['DT_NOTIFIC'] >= (data_atual - pd.Timedelta(days=60))].copy()
    df_va = df[df['DT_NOTIFIC'] >= (data_atual - pd.Timedelta(days=30))].copy()

    # 10. Formatar colunas de data no formato dd/mm/yyyy
    colunas_data = ['DT_NOTIFIC', 'DT_SIN_PRI', 'DT_NASC', 'DT_ENCERRA', 'DT_DIGITA']
    for col in colunas_data:
        df[col] = pd.to_datetime(df[col], errors='coerce')
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%d/%m/%Y')

    # Filtra os casos onde a coluna 'DT_ENCERRA' está vazia (nula)
    casos_sem_encerramento = df[df['DT_ENCERRA'].isna()]


    # 11. Salvar o resultado final 
    # df_ve.to_excel('chico_filtrado_ve.xlsx', index=False, engine='openpyxl')
    # df_va.to_excel('chico_filtrado_va.xlsx', index=False, engine='openpyxl')

    return df_ve, df_va, casos_sem_encerramento