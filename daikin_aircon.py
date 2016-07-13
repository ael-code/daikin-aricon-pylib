import socket
import socketserver
import threading
import time
import urllib.parse
import logging
import urllib3


DSCV_TXT = "DAIKIN_UDP/common/basic_info"
DSCV_PRT = 30050
RET_MSG_OK = b'OK'
RET_MSG_PARAM_NG = b'PARAM NG'
RET_MSG_ADV_NG= b'ADV_NG'

log = logging.getLogger("dainkin_aircon")


class Aircon():

    mappings = [
            ('ver', 'firmware_version'),
            ('name', 'name'),
            ('pow', 'power'),
            ('mac', 'mac'),
            ('led', 'led'),
            ('type', 'type'),
            ('region', 'region')
            ]

    def __init__(self, **args):
        if 'host' in args:
            self.host = args['host']
        else:
            self.host = None

        for name, prop in self.mappings:
            v = args[name] if name in args else None
            try:
                parse_func = getattr(self, '_parse_'+prop)
                v = parse_func(v)
            except(AttributeError):
                pass
            setattr(self, prop, v)

        self._raw_data = args
        self._http_conn = None

    @classmethod
    def _parse_power(cls, v):
        return bool(v)

    @classmethod
    def _parse_name(cls, v):
        return urllib.parse.unquote(v)

    @classmethod
    def _parse_led(cls, v):
        return bool(v)

    def set_control_info(self, params, update=True):
        if update:
            cinfo = self.get_control_info()
            cinfo.update(params)
            params = cinfo
        self.send_request('GET', '/aircon/set_control_info', fields=params)

    def get_control_info(self):
        return self.send_request('GET', '/aircon/get_control_info')

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
        basic_info = {'host': self.host,
                      'mac': self.mac}
        return "<Aircon: {}>".format(basic_info)


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

    discovered = []

    class UDPRequestHandler(socketserver.BaseRequestHandler):

        def handle(self):
            log.debug("Discovery: received response from {} - '{}'".format(self.client_address[0], self.request[0]))
            resp = process_response(self.request[0])
            resp['host'] = self.client_address[0]
            aircon = Aircon(**resp)
            discovered.append(aircon)


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
