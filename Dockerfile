FROM python:3.11-alpine3.16

WORKDIR /usr/src

RUN pip install prometheus_client pyasic==0.39.4 \
    # remove temporary files
    && rm -rf /root/.cache/ \
    && find / -name '*.pyc' -delete

COPY ./asic.py /asic.py

EXPOSE 9904
ENTRYPOINT ["/usr/local/bin/python", "-u", "/asic.py"]

# HELP
# docker build -t vaa12345/prometheus-asic:0.2 .
