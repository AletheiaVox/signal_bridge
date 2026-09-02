"""A minimal fake Intiface Central speaking Buttplug protocol v4 over websockets.

Enough of the protocol for Signal Bridge's client library: handshake, device
list, scanning, OutputCmd, StopCmd. Test hooks let a scenario drop a device,
re-add it, or kill the connection, the way real Bluetooth does.
"""
import asyncio
import json
import websockets


def lush(idx=0):
    return {
        "DeviceName": "Lovense Lush",
        "DeviceIndex": idx,
        "DeviceMessageTimingGap": 0,
        "DeviceFeatures": {
            "0": {"FeatureIndex": 0, "FeatureDescription": "Vibrator",
                  "Output": {"Vibrate": {"Value": [0, 20]}}},
        },
    }


def gravity(idx=1):
    return {
        "DeviceName": "Lovense Gravity",
        "DeviceIndex": idx,
        "DeviceMessageTimingGap": 0,
        "DeviceFeatures": {
            "0": {"FeatureIndex": 0, "FeatureDescription": "Vibrator",
                  "Output": {"Vibrate": {"Value": [0, 20]}}},
            "1": {"FeatureIndex": 1, "FeatureDescription": "Thruster",
                  "Output": {"Oscillate": {"Value": [0, 20]}}},
        },
    }


class FakeIntiface:
    def __init__(self, port: int):
        self.port = port
        self.devices: dict[int, dict] = {}
        self.commands: list[tuple] = []      # (device_index, feature, type, value) or (device_index, "stop")
        self.conn = None
        self.server = None
        self.clients_seen = 0
        self.reject_output = False           # simulate a device that errors on every command

    # -- lifecycle -----------------------------------------------------------
    async def start(self):
        self.server = await websockets.serve(self._handler, "127.0.0.1", self.port)

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        self.conn = None

    async def drop_connection(self):
        """Kill the current client's socket without a Buttplug-level goodbye."""
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    # -- device hooks -----------------------------------------------------------
    async def remove_device(self, idx: int):
        self.devices.pop(idx, None)
        await self._push_device_list()

    async def add_device(self, info: dict):
        self.devices[info["DeviceIndex"]] = info
        await self._push_device_list()

    async def _push_device_list(self):
        if self.conn is not None:
            try:
                await self.conn.send(json.dumps([{"DeviceList": {"Id": 0, "Devices": self._devices_wire()}}]))
            except Exception:
                pass

    def _devices_wire(self):
        return {str(i): d for i, d in self.devices.items()}

    # -- protocol -----------------------------------------------------------------
    async def _handler(self, ws):
        self.conn = ws
        self.clients_seen += 1
        try:
            async for raw in ws:
                out = []
                for msg in json.loads(raw):
                    (mtype, body), = msg.items()
                    mid = body.get("Id", 0)
                    out.append(self._respond(mtype, body, mid))
                await ws.send(json.dumps(out))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if self.conn is ws:
                self.conn = None

    def _respond(self, mtype, body, mid):
        ok = {"Ok": {"Id": mid}}
        if mtype == "RequestServerInfo":
            return {"ServerInfo": {"Id": mid, "ServerName": "Fake Intiface", "MaxPingTime": 0,
                                   "ProtocolVersionMajor": 4, "ProtocolVersionMinor": 0}}
        if mtype == "RequestDeviceList":
            return {"DeviceList": {"Id": mid, "Devices": self._devices_wire()}}
        if mtype in ("StartScanning", "StopScanning", "Ping"):
            return ok
        if mtype == "OutputCmd":
            idx = body["DeviceIndex"]
            if idx not in self.devices or self.reject_output:
                return {"Error": {"Id": mid, "ErrorMessage": f"Device {idx} not connected", "ErrorCode": 4}}
            (otype, cmd), = body["Command"].items()
            self.commands.append((idx, body["FeatureIndex"], otype, cmd["Value"]))
            return ok
        if mtype == "StopCmd":
            idx = body.get("DeviceIndex")
            if idx is not None and idx not in self.devices:
                return {"Error": {"Id": mid, "ErrorMessage": f"Device {idx} not connected", "ErrorCode": 4}}
            self.commands.append((idx, "stop"))
            return ok
        return {"Error": {"Id": mid, "ErrorMessage": f"Unhandled {mtype}", "ErrorCode": 3}}
