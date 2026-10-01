"""EW11 RS485 TCP Socket Hub for Samsung SDS Wallpad Lite."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from .const import (
    CMD_ENERGY_STATE,
    CMD_THERMOSTAT_POWER,
    CMD_THERMOSTAT_STATE,
    CMD_THERMOSTAT_TEMP,
    HEADER_WALLPAD_CMD,
    HEADER_WALLPAD_STATE,
)

_LOGGER = logging.getLogger(__name__)


def calculate_checksum(data: bytes | bytearray) -> int:
    """Calculate Samsung SDS RS485 checksum (XOR of all bytes & 0x7F)."""
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum & 0x7F


def verify_checksum(packet: bytes | bytearray) -> bool:
    """Verify Samsung SDS RS485 packet checksum."""
    checksum = 0
    for byte in packet:
        checksum ^= byte
    return (checksum & 0x7F) == 0


class SDSWallpadHub:
    """Hub communicating with EW11 via TCP socket."""

    def __init__(self, host: str, port: int, power_decimal: int = 2) -> None:
        """Initialize the hub."""
        self.host = host
        self.port = port
        self.power_decimal = power_decimal

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._running = False
        self._task: asyncio.Task | None = None

        # Callbacks
        # thermostat_callbacks[room_id] = list of Callable[[bool, float, float], None]
        # (power_on, target_temp, current_temp)
        self._thermostat_callbacks: dict[int, list[Callable[[bool, float, float], None]]] = {
            i: [] for i in range(1, 6)
        }
        # power_callbacks = list of Callable[[float], None]
        self._power_callbacks: list[Callable[[float], None]] = []

        # Last known states
        self.thermostat_states: dict[int, dict] = {
            i: {"power": False, "target": 22.0, "current": 22.0} for i in range(1, 6)
        }
        self.power_consumption: float = 0.0

    @property
    def is_connected(self) -> bool:
        """Return socket connection status."""
        return self._connected

    def register_thermostat_callback(
        self, room_id: int, callback: Callable[[bool, float, float], None]
    ) -> None:
        """Register callback for thermostat state updates."""
        if room_id in self._thermostat_callbacks:
            self._thermostat_callbacks[room_id].append(callback)

    def register_power_callback(self, callback: Callable[[float], None]) -> None:
        """Register callback for power consumption updates."""
        self._power_callbacks.append(callback)

    async def start(self) -> None:
        """Start the hub socket listener."""
        self._running = True
        self._task = asyncio.create_task(self._socket_loop())

    async def stop(self) -> None:
        """Stop the hub socket listener."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._disconnect()

    async def _disconnect(self) -> None:
        """Close connection."""
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    async def _socket_loop(self) -> None:
        """Continuous connection and reading loop with auto-reconnect."""
        buffer = bytearray()

        while self._running:
            try:
                _LOGGER.info(
                    "Connecting to Samsung SDS EW11 socket at %s:%s...",
                    self.host,
                    self.port,
                )
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), timeout=10.0
                )
                self._connected = True
                _LOGGER.info(
                    "Successfully connected to Samsung SDS EW11 at %s:%s",
                    self.host,
                    self.port,
                )
                buffer.clear()

                while self._running and self._connected:
                    data = await self._reader.read(256)
                    if not data:
                        _LOGGER.warning("EW11 socket connection closed by remote peer.")
                        break

                    buffer.extend(data)
                    self._process_buffer(buffer)

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.warning(
                    "EW11 socket connection error (%s:%s): %s. Reconnecting in 5s...",
                    self.host,
                    self.port,
                    err,
                )
            finally:
                await self._disconnect()

            if self._running:
                await asyncio.sleep(5.0)

    def _process_buffer(self, buffer: bytearray) -> None:
        """Scan buffer for valid SDS RS485 packets."""
        while len(buffer) >= 4:
            # SDS state packet always starts with 0xB0
            # SDS query/command packet starts with 0xAE or 0xAA etc.
            first_byte = buffer[0]

            if first_byte == HEADER_WALLPAD_STATE:
                cmd = buffer[1]
                # 1. Thermostat state: B0 7C [room] [power] [target] [current] [00] [parity] (8 bytes)
                if cmd == CMD_THERMOSTAT_STATE:
                    if len(buffer) < 8:
                        return  # Wait for more bytes
                    packet = buffer[:8]
                    if verify_checksum(packet):
                        self._handle_thermostat_packet(packet)
                        del buffer[:8]
                        continue
                    else:
                        # Corrupted or misaligned
                        del buffer[0]
                        continue

                # 2. Energy state: B0 6F [type] [d1] [d2] [d3] [parity] (7 bytes)
                elif cmd == CMD_ENERGY_STATE:
                    if len(buffer) < 7:
                        return  # Wait for more bytes
                    packet = buffer[:7]
                    if verify_checksum(packet):
                        self._handle_energy_packet(packet)
                        del buffer[:7]
                        continue
                    else:
                        del buffer[0]
                        continue

                # Known other 0xB0 packets to discard cleanly
                elif cmd in (0x41, 0x5A, 0x52):  # 4 bytes ACK / status
                    if len(buffer) < 4:
                        return
                    del buffer[:4]
                    continue
                elif cmd == 0x4E:  # Fan (6 bytes)
                    if len(buffer) < 6:
                        return
                    del buffer[:6]
                    continue
                elif cmd == 0x4A:  # Plug (10 bytes)
                    if len(buffer) < 10:
                        return
                    del buffer[:10]
                    continue
                else:
                    # Unknown 0xB0 packet, advance 1 byte
                    del buffer[0]
                    continue

            elif first_byte == HEADER_WALLPAD_CMD:  # 0xAE
                cmd = buffer[1]
                if cmd in (CMD_THERMOSTAT_STATE, CMD_THERMOSTAT_POWER, CMD_THERMOSTAT_TEMP):
                    if len(buffer) < 8:
                        return
                    del buffer[:8]
                    continue
                del buffer[0]
                continue

            elif first_byte == 0xAA:  # Energy query (4 bytes)
                if len(buffer) < 4:
                    return
                del buffer[:4]
                continue

            elif first_byte in (0xAC, 0xAD, 0xC2, 0xC6, 0xAB):
                # Other known wallpad device packets, skip safely
                del buffer[0]
                continue
            else:
                # Noise / sync search
                del buffer[0]

    def _handle_thermostat_packet(self, packet: bytes | bytearray) -> None:
        """Handle 8-byte thermostat state packet."""
        room_id = packet[2]
        if room_id not in self._thermostat_callbacks:
            return

        power_on = bool(packet[3] & 0x01)
        target_temp = float(packet[4])
        current_temp = float(packet[5])

        self.thermostat_states[room_id] = {
            "power": power_on,
            "target": target_temp,
            "current": current_temp,
        }

        _LOGGER.debug(
            "Thermostat [Room %s] State: Power=%s, Target=%s, Current=%s",
            room_id,
            power_on,
            target_temp,
            current_temp,
        )

        for cb in self._thermostat_callbacks[room_id]:
            try:
                cb(power_on, target_temp, current_temp)
            except Exception as err:
                _LOGGER.error("Error in thermostat callback: %s", err)

    def _handle_energy_packet(self, packet: bytes | bytearray) -> None:
        """Handle 7-byte energy state packet."""
        energy_type = packet[2]
        # energy_type 0: Electricity (Power)
        if energy_type != 0:
            return

        try:
            # 6-decimal BCD representation (e.g. 05 49 00 -> "054900")
            raw_hex = packet[3:6].hex()
            divisor = 10**self.power_decimal
            watt = float(raw_hex) / divisor
            self.power_consumption = round(watt, 1)

            _LOGGER.debug(
                "Power consumption: %s W (raw_hex=%s, divisor=%s)",
                self.power_consumption,
                raw_hex,
                divisor,
            )

            for cb in self._power_callbacks:
                try:
                    cb(self.power_consumption)
                except Exception as err:
                    _LOGGER.error("Error in power callback: %s", err)
        except Exception as err:
            _LOGGER.warning("Failed to parse energy packet: %s (%s)", packet.hex(), err)

    async def async_send_thermostat_power(self, room_id: int, power_on: bool) -> bool:
        """Send power command to room thermostat (AE 7D)."""
        if not self._connected or not self._writer:
            _LOGGER.error("Cannot send command: not connected to EW11")
            return False

        # Packet: AE 7D [room] [01/00] 00 00 00 [checksum] (8 bytes)
        raw = bytearray([0xAE, CMD_THERMOSTAT_POWER, room_id, 0x01 if power_on else 0x00, 0x00, 0x00, 0x00])
        cs = calculate_checksum(raw)
        raw.append(cs)

        try:
            self._writer.write(raw)
            await self._writer.drain()
            _LOGGER.debug("Sent Thermostat Power Cmd: %s", raw.hex())
            return True
        except Exception as err:
            _LOGGER.error("Failed to send thermostat power command: %s", err)
            return False

    async def async_send_thermostat_target_temp(self, room_id: int, target_temp: float) -> bool:
        """Send target temperature command to room thermostat (AE 7F)."""
        if not self._connected or not self._writer:
            _LOGGER.error("Cannot send command: not connected to EW11")
            return False

        # Packet: AE 7F [room] [temp] 00 00 00 [checksum] (8 bytes)
        temp_val = int(round(target_temp))
        raw = bytearray([0xAE, CMD_THERMOSTAT_TEMP, room_id, temp_val, 0x00, 0x00, 0x00])
        cs = calculate_checksum(raw)
        raw.append(cs)

        try:
            self._writer.write(raw)
            await self._writer.drain()
            _LOGGER.debug("Sent Thermostat Target Temp Cmd: %s", raw.hex())
            return True
        except Exception as err:
            _LOGGER.error("Failed to send thermostat temp command: %s", err)
            return False
