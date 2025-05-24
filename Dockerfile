FROM python:3.9

# Definir o diretório de trabalho dentro do contêiner
WORKDIR /app

# Atualizar o pip
RUN pip install --upgrade pip

# Instalar dependências do sistema para Pillow, odfpy, etc.
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    libxslt1-dev \
    libxml2-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar o arquivo de requisitos
COPY requirements.txt /app/

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o código do projeto
COPY . /app/

# Expor a porta do Streamlit
EXPOSE 8501

# Rodar o app com Streamlit
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
