import logging
import urllib


log = logging.getLogger(__name__)


def parse_basic_info(x):
    integers = ['port', 'err', 'pv']
    booleans = ['pow', 'led']
    parse_data(x, integers=integers, booleans=booleans)
    x['name'] = urllib.parse.unquote(x['name'])
    return x


def parse_sensor_info(x):
    integers = ['err']
    temps = ['hhum', 'htemp', 'otemp']
    parse_data(x, integers=integers, temps=temps)
    return x


ctrl_integers = ['alert', 'mode', 'b_mode']
ctrl_temps = ['shum', 'stemp', 'b_shum']
ctrl_booleans = ['pow']

def parse_control_info(x):
    parse_data(x, integers=ctrl_integers, temps=ctrl_temps, booleans=ctrl_booleans)
    return x

def format_control_info(x):
    format_data(x, integers=ctrl_integers, temps=ctrl_temps, booleans=ctrl_booleans)
    return x


def parse_data(x, integers=[],
                  booleans=[],
                  temps=[]):

    for field in integers:
        try:
            x[field] = int(x[field])
        except ValueError as e:
            log.exception("failed to parse field '{}': {}".format(field, e.message))

    for field in booleans:
        try:
            x[field] = bool(int(x[field]))
        except ValueError as e:
            log.exception("Failed to parse field '{}': {}".format(field, e.message))

    for field in temps:
        try:
            x[field] = parse_temperature(x[field])
        except ValueError:
            log.exception(("Failed to parse field {{'{}':'{}'}}."
                           "A temperature was expected").format(field, x[field]))
            pass


def format_data(x, strict=True,
                integers=[],
                booleans=[],
                temps=[]):

    for field in integers:
        try:
            x[field] = str(int(x[field]))
        except KeyError:
            if not strict:
                pass

    for field in booleans:
        try:
            x[field] = str(int(bool(x[field])))
        except KeyError:
            if not strict:
                pass

    for field in temps:
        try:
            x[field] = str(float(x[field]))
        except KeyError:
            if not strict:
                pass


def parse_temperature(temp):
        try:
            return float(temp)
        except ValueError:
            if temp == '-' or temp == '--':
                return None
            else:
                raise
