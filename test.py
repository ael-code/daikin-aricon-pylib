import daikin_aircon
from pprint import pprint

discovered = daikin_aircon.discover()
pprint(discovered)
print('name: '+discovered[0].name)
print('fw_version: '+discovered[0].firmware_version)
