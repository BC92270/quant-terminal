FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates g++ mono-mcs mono-runtime nodejs npm python3 rustc \
 && npm install --global typescript@5.6.3 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/* /root/.npm

RUN mkdir -p /opt/quant-backtest \
 && chown -R 65532:65532 /opt/quant-backtest
COPY runner.py /opt/quant-backtest/runner.py

USER 65532:65532
WORKDIR /opt/quant-backtest
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
LABEL org.quant-terminal.component="backtest-strategy-sandbox" \
      org.quant-terminal.protocol="quant-strategy-jsonl-2" \
      org.quant-terminal.research-only="true"
ENTRYPOINT ["python3", "/opt/quant-backtest/runner.py"]
