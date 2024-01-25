# Prometheus asic metrics exporter

Exporter for the [Prometheus metrics](https://prometheus.io/) based on [Pyasic](https://github.com/UpstreamData/pyasic) library. Currently tested only with Whatsminer M50 series. Should work with all generations.

## Install via docker

Docker image is here: https://hub.docker.com/r/vaa12345/prometheus-asic

Example docker-compose.yml:

```yml
version: '3'
services:
  prometheus_asic-exporter:
    image: vaa12345/prometheus-asic:latest
    container_name: prometheus_asic-exporter
    environment:
       - ASIC_NETWORKS=mylocation:192.168.2.0
    ports:
      - "127.0.0.1:9904:9904"
    restart: unless-stopped
```

Define `ASIC_NETWORKS` environment variable according to the template: location1_name:ip_network1, location2_name:ip_network2, ...

Location names will be displayed in grafana and you can filter by them.

Other optional variables:
- `ASIC_REFRESH_INTERVAL`: (Optional) The refresh interval of the metrics. The default is `60` seconds.
- `ASIC_EXPORTER_PORT`: (Optional) The address the exporter should listen on. The default is `9904`.
- `ASIC_EXPORTER_ADDRESS`: (Optional) The address the exporter should listen on. The default is to listen on all addresses.

Add collector to prometheus.yml config
```shell
  - job_name: asic
    scrape_interval: 60s
    static_configs:
    - targets: ['localhost:9904']
```
scrape_interval is 60 second by default in asic exporter and defined via ASIC_REFRESH_INTERVAL. Don't set this value too low. Depending on the number of your ASICs, it takes time to receive data. Usually from 15 to 30 seconds.

## Grafana dashboard

Example of Grafana dashboard in Asic monitor.json file

![](./grafana.png)
