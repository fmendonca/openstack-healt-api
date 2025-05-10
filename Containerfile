FROM registry.access.redhat.com/ubi9/python-39

LABEL maintainer="seu@email.com"
WORKDIR /app

# Copia arquivos da aplicação
COPY requirements.txt ./
COPY app.py ./

# Instala dependências
RUN pip install --no-cache-dir -r requirements.txt

# Expõe a porta
EXPOSE 8080

# Comando de execução
CMD ["python", "app.py"]
