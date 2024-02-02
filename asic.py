import os
import time
import prometheus_client
import asyncio # asyncio for handling the async part
from pyasic.network import MinerNetwork # miner network handles the scanning
from datetime import datetime
import ipaddress

class AppMetrics:
    """
    Representation of Prometheus metrics and loop to fetch and transform
    pyasic data into Prometheus metrics.
    """

    def __init__(self, refresh_interval, asic_networks):
        self.refresh_interval = refresh_interval
        self.asic_networks = asic_networks
        self.data = {}
        self.alive_miner_ips = []
        self.metric_prefix = 'asic_'
        self.metrics = {}


    def parse_asic_networks(self, asic_networks):
        '''
        Parse ASIC_NETWORKS os environ and return dict with asic localtion name and IP range for later scanning

        asic_networks may two format variations:
        1. ip_range. Location name will be add as 'default'. For example 192.168.0.1, by default mask is /24
        2. splited 'location_name1:ip_range1, location_name2:ip_range2, ...'
        '''
        
        asic_location_and_iprange = {}

        # split if two or more ranges defined
        for asic_network in list(asic_networks.replace(' ', '').split(',')):

            if ':' not in asic_network:
                asic_location_and_iprange['default'] = asic_network
            else:
                asic_localtion, iprange = asic_network.split(':')
                asic_location_and_iprange[asic_localtion] = iprange

        return asic_location_and_iprange


    def add_or_update_metric(self, name, labels, value):
        '''
        Export metric to prometheus client or generate exception

        Parameters:
            name (str): metric name
            labels (dict): metric labels, keys are label names, values are label values
            value (int or str): metric value
        '''
        
        try:
            # Metric name in lower case
            name = self.metric_prefix + name.replace('-', '_').replace(' ', '_').replace('.', '').replace('/', '_').lower()
            label_names = list(labels.keys())
            label_values = labels.values()

            # Create metric if it does not exist
            if name not in self.metrics:
                print('{} Add metric {}'.format(datetime.now(), name))
                metric_desc = name.replace('_', ' ')
                self.metrics[name] = prometheus_client.Gauge(name, metric_desc, label_names)

            # if exist check availability
            # if some miners from previous scan are offline and then remove metric and set availability variable to 0 (Offline)
            if labels['ip'] not in self.alive_miner_ips:

                if name == self.metric_prefix + 'miner_info': # don't erase or update miner_info metric
                    pass
                
                elif name == self.metric_prefix + 'miner_availability':
                    print('{} Set available status to Offline for metric {}, label_values: {}, value: {}'.format(datetime.now(), name, label_values, 0))
                    print('{} Metric: '.format(datetime.now()), self.metrics[name])
                    self.metrics[name].labels(*label_values).set(0)
                else:
                    print('{} Remove metric {}, label_values: {}'.format(datetime.now(), name, label_values))
                    self.metrics[name].remove(*label_values)
            else:
                self.metrics[name].labels(*label_values).set(value)
            
        except Exception as e:
            print('{} Error updating metric {}, label_values: {}, value: {}'.format(datetime.now(), name, label_values, value))
            print('{} Exception: {}'.format(datetime.now(), str(e)))
            pass
        

    async def run_metrics_loop(self):
        """Metrics fetching loop"""

        self.asic_networks = self.parse_asic_networks(self.asic_networks)
        
        while True:
            await self.collect()
            time.sleep(self.refresh_interval)

            
    def get_location_by_ip(self, ip):
        
        for location_name, ip_range in self.asic_networks.items():

            if ipaddress.ip_address(ip) in ipaddress.ip_network(ip_range):

                return location_name
        

    async def collect(self):
        """
        Scan defined network for miners, get and parse data, export it as prometheus metrics
        """
        ### Scan IP range and store data
        # important: scan_network_for_miners() work with version below 0.39.4
        # pyasic above this version dont work with time.sleep() construction for unknown reason
        # data fetched only once, on second iteration loop freezes during re-scan ip range via scan_network_for_miners()

        asic_ips = []
        for ip_range in list(self.asic_networks.values()):
            asic_ips += (list(ipaddress.ip_network(ip_range).hosts()))

        network = MinerNetwork(asic_ips)
        miners = await network.scan_network_for_miners() # scan the network for miners
        
        self.alive_miner_ips = [miner.ip for miner in miners]

        # grabbing data by separate category in parallel
        miner_info = await asyncio.gather(*[miner.api.get_miner_info() for miner in miners])
        devdetails = await asyncio.gather(*[miner.api.devdetails() for miner in miners])
        devs = await asyncio.gather(*[miner.api.devs() for miner in miners])
        error_code = await asyncio.gather(*[miner.api.get_error_code() for miner in miners])
        summary = await asyncio.gather(*[miner.api.summary() for miner in miners])
        status = await asyncio.gather(*[miner.api.status() for miner in miners])
        psu = await asyncio.gather(*[miner.api.get_psu() for miner in miners])
        pools = await asyncio.gather(*[miner.api.pools() for miner in miners])

        # create self.data dict, miner ip is primary key
        for index, value in enumerate(self.alive_miner_ips):
            # add first category to emtpy dict
            # not work via update method
            self.data[value] = {'miner_info': miner_info[index]}

        for index, value in enumerate(self.alive_miner_ips):
            # add second and other categories via update
            self.data[value].update({'devdetails': devdetails[index]})

        for index, value in enumerate(self.alive_miner_ips):
            self.data[value].update({'devs': devs[index]})

        for index, value in enumerate(self.alive_miner_ips):
            self.data[value].update({'error_code': error_code[index]})

        for index, value in enumerate(self.alive_miner_ips):
            self.data[value].update({'summary': summary[index]})

        for index, value in enumerate(self.alive_miner_ips):
            self.data[value].update({'status': status[index]})

        for index, value in enumerate(self.alive_miner_ips):
            self.data[value].update({'psu': psu[index]})

        for index, value in enumerate(self.alive_miner_ips):
            self.data[value].update({'pools': pools[index]})

        # set availability variable to online
        for index, value in enumerate(self.alive_miner_ips):
            self.data[value].update({'availability': 1})

        for index, value in enumerate(self.alive_miner_ips):
            self.data[value].update({'location_name': self.get_location_by_ip(value)})

        ### Parse data and update prometheus metrics
        for asic_ip, properties in self.data.items():
            
            ### miner info block ###
            base_labels = {'ip': asic_ip, 'location': properties['location_name']}

            self.add_or_update_metric('miner_availability', base_labels, properties['availability'])
            
            miner_info_labels = base_labels | {'mac': properties['miner_info']['Msg']['mac'],
                                               'model_name': properties['devdetails']['DEVDETAILS'][0]['Model'],
                                               'serial_number': properties['miner_info']['Msg']['minersn'],
                                               'firmware_version': properties['status']['Msg']['FirmwareVersion']
                                               }
            self.add_or_update_metric('miner_info', miner_info_labels, 1)

            ### miner status block ###
            # if some hashboard return not alive status then break from cycle
            while True:
                if properties['devs']['DEVS'][0]['Status'] != 'Alive':
                    miner_status = properties['devs']['DEVS'][0]['Status']
                    break
                elif properties['devs']['DEVS'][1]['Status'] != 'Alive':
                    miner_status = properties['devs']['DEVS'][1]['Status']
                    break
                elif properties['devs']['DEVS'][2]['Status'] != 'Alive':
                    miner_status = properties['devs']['DEVS'][2]['Status']
                    break
                else:
                    miner_status = 'Alive'
                    break
            
            # concatenate two dicts
            status_labels = base_labels | \
                            {'power_mode': properties['summary']['SUMMARY'][0]['Power Mode'],
                            'error_code': str(properties['error_code']['Msg']['error_code']),
                            'status': miner_status
                            }

            self.add_or_update_metric('miner_status', status_labels, 1) 
            # upfreq property in status section missing on some miners, we need check upfreq complete property on each hashboard
            self.add_or_update_metric('miner_status_upfreq', base_labels, properties['devs']['DEVS'][0]['Upfreq Complete'] and \
                                                                    properties['devs']['DEVS'][1]['Upfreq Complete'] and \
                                                                    properties['devs']['DEVS'][2]['Upfreq Complete'])
            self.add_or_update_metric('miner_status_ths_rt', base_labels, properties['summary']['SUMMARY'][0]['HS RT'])
            self.add_or_update_metric('miner_status_power', base_labels, properties['summary']['SUMMARY'][0]['Power'])
            self.add_or_update_metric('miner_status_power_limit', base_labels, properties['summary']['SUMMARY'][0]['Power Limit'])
            self.add_or_update_metric('miner_status_input_voltage', base_labels, properties['psu']['Msg']['vin'])
            self.add_or_update_metric('miner_status_uptime', base_labels, properties['summary']['SUMMARY'][0]['Uptime'])
            self.add_or_update_metric('miner_status_elapsed_time', base_labels, properties['summary']['SUMMARY'][0]['Elapsed'])

            ### miner temperature block ###
            self.add_or_update_metric('miner_temperature_env_temperature', base_labels, properties['summary']['SUMMARY'][0]['Env Temp'])
            self.add_or_update_metric('miner_temperature_avg_temperature', base_labels, properties['summary']['SUMMARY'][0]['Temperature'])
            self.add_or_update_metric('miner_temperature_psu_temperature', base_labels, properties['psu']['Msg']['temp0'])
            self.add_or_update_metric('miner_temperature_left_board_temperature', base_labels, properties['devs']['DEVS'][0]['Temperature'])
            self.add_or_update_metric('miner_temperature_left_board_chip_avg_temperature', base_labels, properties['devs']['DEVS'][0]['Chip Temp Avg'])
            self.add_or_update_metric('miner_temperature_center_board_temperature', base_labels, properties['devs']['DEVS'][1]['Temperature'])
            self.add_or_update_metric('miner_temperature_center_board_avg_chip_temperature', base_labels, properties['devs']['DEVS'][1]['Chip Temp Avg'])
            self.add_or_update_metric('miner_temperature_right_board_temperature', base_labels, properties['devs']['DEVS'][2]['Temperature'])
            self.add_or_update_metric('miner_temperature_right_board_avg_chip_temperature', base_labels, properties['devs']['DEVS'][2]['Chip Temp Avg'])
            self.add_or_update_metric('miner_temperature_chip_min', base_labels, properties['summary']['SUMMARY'][0]['Chip Temp Min'])
            self.add_or_update_metric('miner_temperature_chip_max', base_labels, properties['summary']['SUMMARY'][0]['Chip Temp Max'])
            self.add_or_update_metric('miner_temperature_chip_avg', base_labels, properties['summary']['SUMMARY'][0]['Chip Temp Avg'])

            ### miner fans block ###
            self.add_or_update_metric('miner_fans_fan_speed_in', base_labels, properties['summary']['SUMMARY'][0]['Fan Speed In'])
            self.add_or_update_metric('miner_fans_fan_speed_out', base_labels, properties['summary']['SUMMARY'][0]['Fan Speed Out'])
            self.add_or_update_metric('miner_fans_psu_fan_speed', base_labels, properties['psu']['Msg']['fan_speed'])

            ### pool status block ###
            pool_labels = base_labels | {'url': properties['pools']['POOLS'][0]['URL'],
                        'status': properties['pools']['POOLS'][0]['Status'],
                        'user': properties['pools']['POOLS'][0]['User'],
                        }

            self.add_or_update_metric('pool_status', pool_labels, 1)
            self.add_or_update_metric('pool_status_last_share_time', base_labels, properties['pools']['POOLS'][0]['Last Share Time'])
            self.add_or_update_metric('pool_status_reject_rate', base_labels, properties['pools']['POOLS'][0]['Pool Rejected%'])


async def main():

    # Validate configuration
    exporter_address = os.environ.get("ASIC_EXPORTER_ADDRESS", "0.0.0.0")
    exporter_port = int(os.environ.get("ASIC_EXPORTER_PORT", 9904))
    refresh_interval = int(os.environ.get("ASIC_REFRESH_INTERVAL", 60))

    class UnconfiguredEnvironment(Exception):
        """base class for new exception"""
        pass

    if not os.environ.get("ASIC_NETWORKS"):
        raise UnconfiguredEnvironment('ASIC_NETWORKS environ variable must be set')

    asic_networks = os.environ.get("ASIC_NETWORKS")

    app_metrics = AppMetrics(
        refresh_interval=refresh_interval,
        asic_networks=asic_networks,
    )

    # Start Prometheus server
    prometheus_client.start_http_server(exporter_port, exporter_address)
    print("{} Server listening in http://{}:{}/metrics".format(datetime.now(), exporter_address, exporter_port))
    await app_metrics.run_metrics_loop()


if __name__ == '__main__':

    asyncio.run(main())