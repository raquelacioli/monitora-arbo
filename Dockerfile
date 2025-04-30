# Usar a imagem oficial do Python como base
FROM python:3.9-slim

# Definir o diretório de trabalho dentro do contêiner
WORKDIR /app


# Instala dependências do sistema
RUN apt-get update && apt-get install -y build-essential python3-dev libffi-dev default-libmysqlclient-dev gcc

# Copiar o arquivo de requisitos e o script para dentro do contêiner
COPY requirements.txt /app/
COPY process_data.py /app/
COPY dados_salvos /app/
COPY temp_upload /app/

# COPY arquivos/CHIKO2025.xls /app/
COPY app.py /app/

# Instalar as dependências
RUN pip install --no-cache-dir -r requirements.txt


EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
