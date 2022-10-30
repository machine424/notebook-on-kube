FROM python:3.10

WORKDIR /app

ARG HELM_VERSION=v3.10.1
ARG HELM_FILENAME="helm-${HELM_VERSION}-linux-amd64.tar.gz"
RUN wget https://get.helm.sh/${HELM_FILENAME} && \
    tar zxvf ${HELM_FILENAME} && mv linux-amd64/helm /usr/local/bin/ && \
    rm ${HELM_FILENAME} && rm -r linux-amd64/

ARG KUBE_VERSION=v1.22.0
RUN curl -L https://storage.googleapis.com/kubernetes-release/release/${KUBE_VERSION}/bin/linux/amd64/kubectl -o /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl

COPY requirements.txt requirements.txt

RUN pip install --prefer-binary --no-cache-dir -r requirements.txt

COPY . .

RUN pip install --prefer-binary --no-cache-dir -e .

ENTRYPOINT ["uvicorn"]
CMD ["notebook_on_kube:app", "--host", "0.0.0.0"]