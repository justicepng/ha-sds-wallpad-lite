"""EW11 RS485 TCP Socket Hub for Samsung SDS Wallpad Lite."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import socket
import time
from typing import Any, Callable

from .const import (
    CMD_DEVICE_SCAN,
    CMD_ENERGY_STATE,
    CMD_THERMOSTAT_POWER,
    CMD_THERMOSTAT_STATE,
    CMD_THERMOSTAT_TEMP,
    HEADER_ENERGY,
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


@dataclass
class QueuedCommand:
    """Class for tracking pending RS485 commands with retry."""

    cmd_type: str  # "power" or "temp"
    room_id: int
    target_value: Any  # bool for power, int for temp
    packet: bytes
    created_at: float
    last_sent_at: float = 0.0
    retries: int = 0


class SDSWallpadHub:
    """Hub communicating with EW11 via TCP socket with robust command queue."""

    def __init__(self, host: str, port: int, power_decimal: int = 2) -> None:
        """Initialize the hub."""
        self.host = host
        self.port = port
        self.power_decimal = power_decimal

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._running = False
        self._socket_task: asyncio.Task | None = None
        self._retry_task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()

        # Command Queue: (room_id, cmd_type) -> QueuedCommand
        self._queue: dict[tuple[int, str], QueuedCommand] = {}

        # Callbacks
        self._thermostat_callbacks: dict[int, list[Callable[[bool, float, float], None]]] = {
            i: [] for i in range(1, 6)
        }
        self._power_callbacks: list[Callable[[float], None]] = []

        # Last known states
        self.thermostat_states: dict[int, dict] = {
            i: {"power": False, "target": 22.0, "current": 22.0} for i in range(1, 6)
        }
        self.power_consumption: float = 0.0
        self._consecutive_energy_scans: int = 0
        self._last_energy_ack_sent: float = 0.0
        self._last_energy_packet_received: float = 0.0
        self._last_data_received_at: float = 0.0
        self._watchdog_task: asyncio.Task | None = None

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
        """Start the hub socket listener and background workers."""
        self._running = True
        self._last_data_received_at = time.time()
        self._last_energy_packet_received = time.time()
        self._socket_task = asyncio.create_task(self._socket_loop())
        self._retry_task = asyncio.create_task(self._retry_loop())
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop(self) -> None:
        """Stop the hub socket listener and workers."""
        self._running = False
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass
        if self._socket_task:
            self._socket_task.cancel()
            try:
                await self._socket_task
            except asyncio.CancelledError:
                pass
        await self._disconnect()

    async def _disconnect(self) -> None:
        """Close connection safely without hanging."""
        self._connected = False
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer:
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
            except Exception:
                pass

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
                self._last_data_received_at = time.time()

                # Enable TCP Keepalive
                sock = self._writer.get_extra_info("socket")
                if sock:
                    try:
                        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                        if hasattr(socket, "TCP_KEEPIDLE"):
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 5)
                        if hasattr(socket, "TCP_KEEPINTVL"):
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
                        if hasattr(socket, "TCP_KEEPCNT"):
                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                    except Exception:
                        pass

                _LOGGER.info(
                    "Successfully connected to Samsung SDS EW11 at %s:%s",
                    self.host,
                    self.port,
                )
                buffer.clear()

                while self._running and self._connected:
                    # SDS RS485 bus streams packets continuously (< 1s interval).
                    # If 10s pass without bytes, the socket is dead/hung (half-open).
                    try:
                        data = await asyncio.wait_for(self._reader.read(256), timeout=10.0)
                    except asyncio.TimeoutError:
                        _LOGGER.warning(
                            "No RS485 packets received from EW11 for 10s. Socket appears frozen/dead. Triggering auto-reconnect..."
                        )
                        break

                    if not data:
                        _LOGGER.warning("EW11 socket connection closed by remote peer.")
                        break

                    self._last_data_received_at = time.time()
                    buffer.extend(data)
                    self._process_buffer(buffer)

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.warning(
                    "EW11 socket connection error (%s:%s): %s. Reconnecting in 3s...",
                    self.host,
                    self.port,
                    err,
                )
            finally:
                await self._disconnect()

            if self._running:
                await asyncio.sleep(3.0)

    async def _watchdog_loop(self) -> None:
        """Watchdog to ensure continuous packet stream and heal zombie connections."""
        while self._running:
            try:
                await asyncio.sleep(5.0)
                now = time.time()

                # 1. Check socket liveness: If connected but no packets for >= 20s, force reset
                if self._connected:
                    idle_time = now - self._last_data_received_at
                    if idle_time > 20.0:
                        _LOGGER.warning(
                            "Watchdog: No RS485 packets for %.1fs (limit 20s). Forcefully resetting socket to heal connection...",
                            idle_time,
                        )
                        await self._disconnect()
                        continue

                # 2. Check energy meter polling: If no energy packets received for >= 30s, inject query
                if self._connected and (now - self._last_energy_packet_received > 30.0):
                    if now - self._last_energy_ack_sent >= 5.0:
                        self._last_energy_ack_sent = now
                        _LOGGER.info(
                            "Watchdog: Energy data stale (>30s). Injecting energy query (AA 6F 00 45)..."
                        )
                        query_packet = bytes([0xAA, 0x6F, 0x00, 0x45])
                        asyncio.create_task(self._send_energy_recovery_query(query_packet))

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error in hub watchdog loop: %s", err)

    async def _retry_loop(self) -> None:
        """Background worker to retry queued commands periodically."""
        while self._running:
            try:
                await asyncio.sleep(0.3)
                if not self._connected or not self._queue:
                    continue

                now = time.time()
                keys_to_remove: list[tuple[int, str]] = []

                # Copy items to safely iterate
                items = list(self._queue.items())
                for key, cmd in items:
                    # Timeout after 20 seconds
                    if now - cmd.created_at > 20.0:
                        _LOGGER.warning(
                            "Thermostat [Room %s %s] command timed out after 20s (sent %s times).",
                            cmd.room_id,
                            cmd.cmd_type,
                            cmd.retries,
                        )
                        keys_to_remove.append(key)
                        continue

                    # Resend if at least 0.3s passed since last transmission
                    if now - cmd.last_sent_at >= 0.3:
                        await self._send_command(cmd)

                for k in keys_to_remove:
                    self._queue.pop(k, None)

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error in retry loop: %s", err)

    async def _send_command(self, cmd: QueuedCommand) -> bool:
        """Send a single RS485 command through the writer."""
        if not self._connected or not self._writer:
            return False

        async with self._send_lock:
            try:
                self._writer.write(cmd.packet)
                await self._writer.drain()
                cmd.last_sent_at = time.time()
                cmd.retries += 1
                _LOGGER.debug(
                    "Sent RS485 command [Room %s %s -> %s] (try #%s): %s",
                    cmd.room_id,
                    cmd.cmd_type,
                    cmd.target_value,
                    cmd.retries,
                    cmd.packet.hex(),
                )
                return True
            except Exception as err:
                _LOGGER.warning("Failed to send command over socket: %s", err)
                return False

    def _trigger_next_queued_send(self) -> None:
        """Trigger immediate send of queued commands right after bus clears."""
        if not self._queue or not self._connected:
            return

        now = time.time()
        for cmd in self._queue.values():
            if now - cmd.last_sent_at >= 0.15:
                asyncio.create_task(self._send_command(cmd))
                break  # Send one command per timing slot to prevent collision

    def _process_buffer(self, buffer: bytearray) -> None:
        """Scan buffer for valid SDS RS485 packets and detect ACKs."""
        while len(buffer) >= 4:
            first_byte = buffer[0]

            if first_byte == HEADER_WALLPAD_STATE:
                cmd = buffer[1]

                # 1. Thermostat state: B0 7C [room] [power] [target] [current] [00] [parity] (8 bytes)
                if cmd == CMD_THERMOSTAT_STATE:
                    if len(buffer) < 8:
                        return
                    packet = buffer[:8]
                    if verify_checksum(packet):
                        self._handle_thermostat_packet(packet)
                        del buffer[:8]
                        # Best timing window: Bus is idle right after state packet!
                        self._trigger_next_queued_send()
                        continue
                    else:
                        del buffer[0]
                        continue

                # 2. Thermostat ACK: B0 7D (Power ACK) or B0 7F (Temp ACK) (8 bytes or 4 bytes)
                elif cmd in (CMD_THERMOSTAT_POWER, CMD_THERMOSTAT_TEMP):
                    if len(buffer) < 4:
                        return
                    room_id = buffer[2]
                    cmd_type = "power" if cmd == CMD_THERMOSTAT_POWER else "temp"
                    key = (room_id, cmd_type)
                    if key in self._queue:
                        q_cmd = self._queue.pop(key)
                        _LOGGER.info(
                            "Thermostat [Room %s %s] ACK received! (Elapsed: %.2fs, retries: %s)",
                            room_id,
                            cmd_type,
                            time.time() - q_cmd.created_at,
                            q_cmd.retries,
                        )
                    del buffer[:4]
                    self._trigger_next_queued_send()
                    continue

                # 3. Energy state: B0 6F [type] [d1] [d2] [d3] [parity] (7 bytes)
                elif cmd == CMD_ENERGY_STATE:
                    if len(buffer) < 7:
                        return
                    packet = buffer[:7]
                    if verify_checksum(packet):
                        self._handle_energy_packet(packet)
                        del buffer[:7]
                        self._trigger_next_queued_send()
                        continue
                    else:
                        del buffer[0]
                        continue

                # Known other 0xB0 packets to discard cleanly
                elif cmd in (0x41, 0x5A, 0x52):
                    if len(buffer) < 4:
                        return
                    if cmd == 0x5A:
                        self._consecutive_energy_scans = 0
                    del buffer[:4]
                    continue
                elif cmd == 0x4E:
                    if len(buffer) < 6:
                        return
                    del buffer[:6]
                    continue
                elif cmd == 0x4A:
                    if len(buffer) < 10:
                        return
                    del buffer[:10]
                    continue
                else:
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

            elif first_byte == HEADER_ENERGY:  # 0xAA (Energy queries: AA 5A or AA 6F)
                if len(buffer) < 4:
                    return
                packet = buffer[:4]
                if verify_checksum(packet):
                    cmd = packet[1]
                    if cmd == CMD_DEVICE_SCAN:
                        self._handle_energy_scan_query()
                    elif cmd == CMD_ENERGY_STATE:
                        self._consecutive_energy_scans = 0
                    del buffer[:4]
                    continue
                else:
                    del buffer[0]
                    continue

            elif first_byte in (0xAC, 0xAD, 0xC2, 0xC6, 0xAB):
                del buffer[0]
                continue
            else:
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

        # Check if pending queued commands are confirmed by this state update
        power_key = (room_id, "power")
        if power_key in self._queue:
            q_cmd = self._queue[power_key]
            if q_cmd.target_value == power_on:
                _LOGGER.info(
                    "Thermostat [Room %s Power -> %s] Confirmed by state packet! (Elapsed: %.2fs, tries: %s)",
                    room_id,
                    power_on,
                    time.time() - q_cmd.created_at,
                    q_cmd.retries,
                )
                self._queue.pop(power_key, None)

        temp_key = (room_id, "temp")
        if temp_key in self._queue:
            q_cmd = self._queue[temp_key]
            if int(round(q_cmd.target_value)) == int(round(target_temp)):
                _LOGGER.info(
                    "Thermostat [Room %s Temp -> %s] Confirmed by state packet! (Elapsed: %.2fs, tries: %s)",
                    room_id,
                    target_temp,
                    time.time() - q_cmd.created_at,
                    q_cmd.retries,
                )
                self._queue.pop(temp_key, None)

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

    def _handle_energy_scan_query(self) -> None:
        """Handle Wallpad energy device scan query (AA 5A 00 70)."""
        self._consecutive_energy_scans += 1
        now = time.time()
        # If Wallpad sends device scan queries >= 2 times, proactively inject
        # Energy Query (AA 6F 00 45) to query the physical meter directly and
        # transition the Wallpad back into its regular 3-utility polling loop.
        if self._consecutive_energy_scans >= 2 and (now - self._last_energy_ack_sent >= 1.5):
            self._last_energy_ack_sent = now
            self._consecutive_energy_scans = 0
            query_packet = bytes([0xAA, 0x6F, 0x00, 0x45])

            _LOGGER.info(
                "Wallpad energy scan loop detected (AA 5A). Injecting energy query (AA 6F 00 45) to resume polling..."
            )
            asyncio.create_task(self._send_energy_recovery_query(query_packet))

    async def _send_energy_recovery_query(self, query_packet: bytes) -> None:
        """Send energy recovery query with RS485 bus turnaround delay."""
        if not self._connected or not self._writer:
            return
        async with self._send_lock:
            try:
                # 20ms delay for RS485 bus turnaround after AA 5A 00 70
                await asyncio.sleep(0.020)
                self._writer.write(query_packet)
                await self._writer.drain()
                _LOGGER.info("Successfully injected energy recovery query: %s", query_packet.hex())
            except Exception as err:
                _LOGGER.warning("Failed to send energy recovery query: %s", err)

    def _handle_energy_packet(self, packet: bytes | bytearray) -> None:
        """Handle 7-byte energy state packet."""
        energy_type = packet[2]
        if energy_type != 0:
            return

        self._consecutive_energy_scans = 0
        self._last_energy_packet_received = time.time()

        try:
            raw_hex = packet[3:6].hex()
            if not raw_hex.isdigit():
                _LOGGER.warning("Energy packet contains non-decimal BCD digits: %s", packet.hex())
                return

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
        """Queue and send power command to room thermostat (AE 7D)."""
        raw = bytearray([0xAE, CMD_THERMOSTAT_POWER, room_id, 0x01 if power_on else 0x00, 0x00, 0x00, 0x00])
        cs = calculate_checksum(raw)
        raw.append(cs)

        now = time.time()
        cmd = QueuedCommand(
            cmd_type="power",
            room_id=room_id,
            target_value=power_on,
            packet=bytes(raw),
            created_at=now,
        )
        self._queue[(room_id, "power")] = cmd

        _LOGGER.info(
            "Queued Thermostat Power Command: Room %s -> %s (packet: %s)",
            room_id,
            "ON" if power_on else "OFF",
            raw.hex(),
        )

        # Attempt immediate send
        return await self._send_command(cmd)

    async def async_send_thermostat_target_temp(self, room_id: int, target_temp: float) -> bool:
        """Queue and send target temperature command to room thermostat (AE 7F)."""
        temp_val = int(round(target_temp))
        raw = bytearray([0xAE, CMD_THERMOSTAT_TEMP, room_id, temp_val, 0x00, 0x00, 0x00])
        cs = calculate_checksum(raw)
        raw.append(cs)

        now = time.time()
        cmd = QueuedCommand(
            cmd_type="temp",
            room_id=room_id,
            target_value=temp_val,
            packet=bytes(raw),
            created_at=now,
        )
        self._queue[(room_id, "temp")] = cmd

        _LOGGER.info(
            "Queued Thermostat Temp Command: Room %s -> %s℃ (packet: %s)",
            room_id,
            temp_val,
            raw.hex(),
        )

        # Attempt immediate send
        return await self._send_command(cmd)
