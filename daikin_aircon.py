import socket
import socketserver
import threading
import time
import logging
import urllib3

import bridge


DSCV_TXT = "DAIKIN_UDP/common/basic_info"
DSCV_PRT = 30050

RET_MSG_OK = b'OK'
RET_MSG_PARAM_NG = b'PARAM NG'
RET_MSG_ADV_NG= b'ADV_NG'

log = logging.getLogger("dainkin_aircon")


class Aircon():

    MODE_AUTO = 0
    MODE_DRY = 2
    MODE_COOL = 3
    MODE_HEAT = 4
    MODE_FAN = 6

    def __init__(self, host):
        self.host = host
        self._http_conn = None

    def get_name(self):
        return self.get_basic_info()['name']

    name = property(get_name)

    def get_mac_address(self):
        return self.get_basic_info()['mac']

    mac_address = property(get_mac_address)

    def get_firmware_version(self):
        return self.get_basic_info()['ver']

    firmware_version = property(get_firmware_version)

    def set_power(self, v):
        self.set_control_info({'pow': v})

    def get_power(self):
        return self.get_control_info()['pow']

    power = property(get_power, set_power)

    def get_target_temp(self):
        return self.get_control_info()['stemp']

    def set_target_temp(self, v):
        self.set_control_info({'stemp': v})

    target_temp = property(get_target_temp, set_target_temp)

    def get_mode(self):
        return self.get_control_info()['mode']

    def set_mode(self, v):
        self.set_control_info({'mode': v})

    mode = property(get_mode, set_mode)

    def get_indoor_temp(self):
        return self.get_sensor_info()['htemp']

    indoor_temp = property(get_indoor_temp)

    def get_outdoor_temp(self):
        return self.get_sensor_info()['otemp']

    outdoor_temp = property(get_outdoor_temp)

    def reboot(self):
        return self.send_request('GET', '/common/reboot')

    def get_raw_basic_info(self):
        return self.send_request('GET', '/common/basic_info')

    def get_basic_info(self):
        return bridge.parse_basic_info(self.get_raw_basic_info())

    def get_raw_sensor_info(self):
        return self.send_request('get', '/aircon/get_sensor_info')

    def get_sensor_info(self):
        return bridge.parse_sensor_info(self.get_raw_sensor_info())

    def set_raw_control_info(self, params, update=True):
        if update:
            cinfo = self.get_raw_control_info()
            minimal_cinfo = {k:cinfo[k] for k in cinfo if k in ['pow','mode','stemp', 'shum','f_rate','f_dir']}
            minimal_cinfo.update(params)
            params = minimal_cinfo
        self.send_request('GET', '/aircon/set_control_info', fields=params)

    def set_control_info(self, params, update=True):
        return self.set_raw_control_info(bridge.format_control_info(params), update)

    def get_raw_control_info(self):
        return self.send_request('GET', '/aircon/get_control_info')

    def get_control_info(self):
        return bridge.parse_control_info(self.get_raw_control_info())

    def send_request(self, method, url, fields=None, headers=None, **urlopen_kw):
        '''Send request to air conditioner

           args and kwargs will be passed to
           `urllib3.request.RequestMethods.request`
        '''
        if self.host == None:
            raise Exception("Cannot send request: host attribute missing")

        if self._http_conn == None:
            self._http_conn = urllib3.PoolManager()

        res = self._http_conn.request(method,
                                      'http://{}{}'.format(self.host, url),
                                      fields=fields,
                                      headers=headers,
                                      **urlopen_kw)
        log.debug("Received response from '{}', data: '{}'".format(self.host,res.data))
        return process_response(res.data)

    def __repr__(self):
        return "<Aircon: '{}'>".format(self.host)


class RespException(Exception):
    pass


def process_response(response):
    '''Transform the air conditioner response into a dictionary

       If the response doesn't starts with
       standard prefix @RESPONSE_PREFIX a RespException will be raised.
    '''
    rsp = response.split(b',')
    if (len(rsp) is 0) or (not rsp[0].startswith(b'ret=')):
        raise RespException("Unrecognized data format for the response")

    ret_msg = rsp[0][4:]
    if ret_msg != RET_MSG_OK:
        if ret_msg == RET_MSG_PARAM_NG:
            raise RespException("Wrong parameters")
        elif ret_msg == RET_MSG_ADV_NG:
            raise RespException("Wrong ADV")
        else:
            raise RespException("Unrecognized return message: '{}'".format(ret_msg))

    # Remove the standard prefix
    rsp = rsp[1:]
    # Transform the dictionary into a response
    rsp = {k.decode():v.decode() for k,v in map(lambda s: s.split(b'='), rsp)}
    return rsp


def discover(waitfor=1,
             timeout=10,
             listen_address="0.0.0.0",
             listen_port=0,
             probe_port=30050,
             probe_address='255.255.255.255',
             probe_attempts=10,
             probe_interval=0.3):

    discovered = {}

    class UDPRequestHandler(socketserver.BaseRequestHandler):

        def handle(self):
            log.debug("Discovery: received response from {} - '{}'".format(self.client_address[0], self.request[0]))
            resp = process_response(self.request[0])
            host = self.client_address[0]
            discovered[host] = resp


    sckt = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sckt.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sckt.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    server = socketserver.ThreadingUDPServer((listen_address, listen_port), UDPRequestHandler)
    server.socket = sckt
    srv_addr, srv_port = server.server_address

    server_thread = threading.Thread(target=server.serve_forever)
    # Exit the server thread when the main thread terminates
    server_thread.daemon = True
    log.debug("Discovery: starting UDP server on {}:{}".format(srv_addr, srv_port))
    server_thread.start()

    for i in range(0, probe_attempts):
        log.debug("Discovery: probe attempt {} on {}:{}".format(i, probe_address, probe_port))
        sckt.sendto(DSCV_TXT.encode(), (probe_address, probe_port))
        log.debug("Discovery: sleeping for {}s".format(probe_interval))
        time.sleep(probe_interval)
        if len(discovered) >= waitfor:
            break

    remaining_time = timeout - (probe_interval * probe_attempts)
    if (remaining_time > 0) and (len(discovered) < waitfor):
        log.debug("Discovery: waiting responses for {}s more".format(remaining_time))
        time.sleep(remaining_time)

    server.shutdown()
    server.server_close()

    return discovered
