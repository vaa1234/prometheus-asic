import os
from os.path import exists
import time
import prometheus_client
import asyncio # asyncio for handling the async part
from pyasic.network import MinerNetwork # miner network handles the scanning
from datetime import datetime

METRICS = {}
metric_prefix = 'asic_'

async def get_miners_data(ip_range: str):
    # Define network range to be used for scanning
    # This can take a list of IPs, a constructor string, or an IP and subnet mask
    network = MinerNetwork(ip_range)

    # Scan the network for miners
    # This function returns a list of miners of the correct type as a class
    miners = await network.scan_network_for_miners()

    miners_ips = [miner.ip for miner in miners]

    # grabbing data by separate category in parallel
    miner_info = await asyncio.gather(*[miner.api.get_miner_info() for miner in miners])
    devdetails = await asyncio.gather(*[miner.api.devdetails() for miner in miners])
    devs = await asyncio.gather(*[miner.api.devs() for miner in miners])
    error_code = await asyncio.gather(*[miner.api.get_error_code() for miner in miners])
    summary = await asyncio.gather(*[miner.api.summary() for miner in miners])
    status = await asyncio.gather(*[miner.api.status() for miner in miners])
    psu = await asyncio.gather(*[miner.api.get_psu() for miner in miners])
    pools = await asyncio.gather(*[miner.api.pools() for miner in miners])

    # create full dataset from grabed data, miner ip is primary key
    data = dict.fromkeys(miners_ips, {})

    for index, (key, value) in enumerate(data.items()):
        # add first category to emtpy dict
        # not work via update method
        data[key] = {'miner_info': miner_info[index]}

    for index, (key, value) in enumerate(data.items()):
        # add second and other categories via update
        data[key].update({'devdetails': devdetails[index]})

    for index, (key, value) in enumerate(data.items()):
        data[key].update({'devs': devs[index]})

    for index, (key, value) in enumerate(data.items()):
        data[key].update({'error_code': error_code[index]})

    for index, (key, value) in enumerate(data.items()):
        data[key].update({'summary': summary[index]})

    for index, (key, value) in enumerate(data.items()):
        data[key].update({'status': status[index]})

    for index, (key, value) in enumerate(data.items()):
        data[key].update({'psu': psu[index]})

    for index, (key, value) in enumerate(data.items()):
        data[key].update({'pools': pools[index]})

    return data
        

async def collect(ip_range):
    # grab all miners data
    data = await get_miners_data(ip_range)

    # parse and add metrics for data
    for asic_ip, properties in data.items():

        ### miner info block ###
        base_labels = {'ip': asic_ip,
                       'mac': properties['miner_info']['Msg']['mac'],
                       'model_name': properties['devdetails']['DEVDETAILS'][0]['Model'],
                       'serial_number': properties['miner_info']['Msg']['minersn'],
                       'firmware_version': properties['status']['Msg']['FirmwareVersion']}
        
        add_metric('miner_info', base_labels, 1)

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
                        'error_code': ' '.join(properties['error_code']['Msg']['error_code']),
                        'status': miner_status
                        }
        
        miner_status_uptime = properties['summary']['SUMMARY'][0]['Uptime']
        miner_status_elapsed_time = properties['summary']['SUMMARY'][0]['Elapsed']

        # upfreq property in status section missing on some miners
        # we need check upfreq complete property on each hashboard
        miner_status_upfreq = properties['devs']['DEVS'][0]['Upfreq Complete'] and \
                                properties['devs']['DEVS'][1]['Upfreq Complete'] and \
                                properties['devs']['DEVS'][2]['Upfreq Complete']
        
        miner_status_ths_rt = round(properties['summary']['SUMMARY'][0]['HS RT'] / 1000000, 2)
        miner_status_power = properties['summary']['SUMMARY'][0]['Power']
        miner_status_power_limit = properties['summary']['SUMMARY'][0]['Power Limit']
        miner_status_efficiency = miner_status_power / miner_status_ths_rt
        miner_status_input_voltage = int(properties['psu']['Msg']['vin']) / 100

        add_metric('miner_status', status_labels, 1) 
        add_metric('miner_status_upfreq', base_labels, miner_status_upfreq)
        add_metric('miner_status_ths_rt', base_labels, miner_status_ths_rt)
        add_metric('miner_status_power', base_labels, miner_status_power)
        add_metric('miner_status_power_limit', base_labels, miner_status_power_limit)
        add_metric('miner_status_efficiency', base_labels, miner_status_efficiency)
        add_metric('miner_status_input_voltage', base_labels, miner_status_input_voltage)
        add_metric('miner_status_uptime', base_labels, miner_status_uptime)
        add_metric('miner_status_elapsed_time', base_labels, miner_status_elapsed_time)

        ### miber temperature block ###
        miner_temperature_env_temperature = properties['summary']['SUMMARY'][0]['Env Temp']
        miner_temperature_avg_temperature = properties['summary']['SUMMARY'][0]['Temperature']
        miner_temperature_psu_temperature = properties['psu']['Msg']['temp0']
        miner_temperature_left_board_temperature = properties['devs']['DEVS'][0]['Temperature']
        miner_temperature_left_board_chip_temperature = properties['devs']['DEVS'][0]['Temperature']
        miner_temperature_center_board_temperature = properties['devs']['DEVS'][1]['Temperature']
        miner_temperature_center_board_chip_temperature = properties['devs']['DEVS'][1]['Chip Temp Avg']
        miner_temperature_right_board_temperature = properties['devs']['DEVS'][2]['Temperature']
        miner_temperature_right_board_chip_temperature = properties['devs']['DEVS'][2]['Chip Temp Avg']

        add_metric('miner_temperature_env_temperature', base_labels, miner_temperature_env_temperature)
        add_metric('miner_temperature_avg_temperature', base_labels, miner_temperature_avg_temperature)
        add_metric('miner_temperature_psu_temperature', base_labels, miner_temperature_psu_temperature)
        add_metric('miner_temperature_left_board_temperature', base_labels, miner_temperature_left_board_temperature)
        add_metric('miner_temperature_left_board_chip_temperature', base_labels, miner_temperature_left_board_chip_temperature)
        add_metric('miner_temperature_center_board_temperature', base_labels, miner_temperature_center_board_temperature)
        add_metric('miner_temperature_center_board_chip_temperature', base_labels, miner_temperature_center_board_chip_temperature)
        add_metric('miner_temperature_right_board_temperature', base_labels, miner_temperature_right_board_temperature)
        add_metric('miner_temperature_right_board_chip_temperature', base_labels, miner_temperature_right_board_chip_temperature)

        ### miner fans block ###
        miner_fans_fan_speed_in = properties['summary']['SUMMARY'][0]['Fan Speed In']
        miner_fans_fan_speed_out = properties['summary']['SUMMARY'][0]['Fan Speed Out']
        miner_fans_psu_fan_speed = properties['psu']['Msg']['fan_speed']

        add_metric('miner_fans_fan_speed_in', base_labels, miner_fans_fan_speed_in)
        add_metric('miner_fans_fan_speed_out', base_labels, miner_fans_fan_speed_out)
        add_metric('miner_fans_psu_fan_speed', base_labels, miner_fans_psu_fan_speed)

        ### pool status block ###
        pool_labels = base_labels | {'url': properties['pools']['POOLS'][0]['URL'],
                       'status': properties['pools']['POOLS'][0]['Status'],
                       'user': properties['pools']['POOLS'][0]['User'],
                       }

        pool_status_last_share_time = properties['pools']['POOLS'][0]['Last Share Time']
        pool_status_reject_rate = properties['pools']['POOLS'][0]['Pool Rejected%']

        add_metric('pool_status', pool_labels, 1)
        add_metric('pool_status_last_share_time', base_labels, pool_status_last_share_time)
        add_metric('pool_status_reject_rate', base_labels, pool_status_reject_rate)
        

def add_metric(name, labels, value):
    '''
    Export metric to prometheus client or generate exception

        Parameters:
            name (str): metric name
            labels (dict): metric labels, keys are label names, values are label values
            value (int or str): metric value
    '''
    global METRICS

    try:
        # Metric name in lower case
        metric = metric_prefix + name.replace('-', '_').replace(' ', '_').replace('.', '').replace('/', '_').lower()
        label_names = list(labels.keys())
        label_values = labels.values()

        # Create metric if it does not exist
        if metric not in METRICS:
            print('add metric {}'.format(metric))
            desc = name.replace('_', ' ')
            METRICS[metric] = prometheus_client.Gauge(metric, f'({value}) {desc}', label_names)

        # Update metric
        METRICS[metric].labels(*label_values).set(value)

    except Exception as e:
        print('Exception:', e)
        pass


async def main():
    """
    Starts a server and exposes the metrics
    """

    # Validate configuration
    exporter_address = os.environ.get("ASIC_EXPORTER_ADDRESS", "0.0.0.0")
    exporter_port = int(os.environ.get("ASIC_EXPORTER_PORT", 9904))
    refresh_interval = int(os.environ.get("ASIC_REFRESH_INTERVAL", 60))

    class UnconfiguredEnvironment(Exception):
        """base class for new exception"""
        pass

    if not os.environ.get("ASIC_IP_RANGE"):
        raise UnconfiguredEnvironment('ASIC_IP_RANGE environ variable must be set')

    ip_range = os.environ.get("ASIC_IP_RANGE")

    # Start Prometheus server
    prometheus_client.start_http_server(exporter_port, exporter_address)
    print(f"Server listening in http://{exporter_address}:{exporter_port}/metrics")

    while True:
        await collect(ip_range)
        time.sleep(refresh_interval)


if __name__ == '__main__':

    asyncio.run(main())