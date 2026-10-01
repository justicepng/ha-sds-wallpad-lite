"""Constants for the Samsung SDS Wallpad Lite integration."""

DOMAIN = "sds_wallpad_lite"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_POWER_DECIMAL = "power_decimal"

DEFAULT_HOST = "192.168.0.16"
DEFAULT_PORT = 8899
DEFAULT_POWER_DECIMAL = 2

# Room mapping (ID to default name)
ROOM_NAMES = {
    1: "거실",
    2: "안방",
    3: "알파룸",
    4: "유진방",
    5: "상수방",
}

# RS485 Protocol Headers
HEADER_WALLPAD_STATE = 0xB0
HEADER_WALLPAD_CMD = 0xAE

CMD_THERMOSTAT_STATE = 0x7C   # B0 7C (8 bytes)
CMD_THERMOSTAT_POWER = 0x7D   # AE 7D (8 bytes)
CMD_THERMOSTAT_TEMP = 0x7F    # AE 7F (8 bytes)
CMD_ENERGY_STATE = 0x6F       # B0 6F (7 bytes)
