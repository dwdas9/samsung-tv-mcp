#!/usr/bin/env python3
"""Find a Samsung TV on your network and pair with it.

Usage:
  python pair.py                 # discover TVs, then pair
  python pair.py 192.168.1.50    # pair a TV by IP

Writes tv_config.json and tv-token.txt next to this script.
Keep the TV on and accept the "Allow" prompt with your remote.
"""
import json
import socket
import sys
import urllib.request
from pathlib import Path

from samsungtvws import SamsungTVWS

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "tv_config.example.json"
CONFIG = HERE / "tv_config.json"
TOKEN = HERE / "tv-token.txt"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def discover(timeout: float = 4.0) -> list:
    msg = "\r\n".join([
        "M-SEARCH * HTTP/1.1",
        "HOST: 239.255.255.250:1900",
        'MAN: "ssdp:discover"',
        "MX: 2",
        "ST: urn:samsung.com:device:RemoteControlReceiver:1",
        "", ""]).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(timeout)
    s.sendto(msg, ("239.255.255.250", 1900))
    found = set()
    try:
        while True:
            _, addr = s.recvfrom(65507)
            found.add(addr[0])
    except socket.timeout:
        pass
    return sorted(found)


def device_info(host: str):
    try:
        with OPENER.open(f"http://{host}:8001/api/v2/", timeout=4) as r:
            return json.loads(r.read().decode())["device"]
    except Exception:
        return None


def main():
    if len(sys.argv) > 1:
        host = sys.argv[1]
    else:
        print("Searching for Samsung TVs...")
        tvs = [(h, device_info(h)) for h in discover()]
        tvs = [(h, d) for h, d in tvs if d]
        if not tvs:
            sys.exit("No TV found. Check it's on and on the same network, "
                     "or pass its IP: python pair.py 192.168.1.50")
        for h, d in tvs:
            print(f"  {h}  {d.get('name')}  {d.get('modelName')}")
        if len(tvs) > 1:
            sys.exit("More than one TV found. Run again with the IP you want.")
        host = tvs[0][0]

    dev = device_info(host)
    if not dev:
        sys.exit(f"No Samsung TV API at http://{host}:8001. Is the TV on? "
                 "On macOS, check System Settings > Privacy & Security > Local Network.")
    print(f"Found {dev.get('name')} ({dev.get('modelName')}) at {host}")
    if dev.get("TokenAuthSupport") != "true":
        print("Warning: this TV doesn't report token auth. Older models may not work.")

    cfg = json.loads((CONFIG if CONFIG.exists() else EXAMPLE).read_text())
    cfg["host"] = host
    cfg["mac"] = dev.get("wifiMac") or cfg.get("mac")
    cfg["broadcast"] = host.rsplit(".", 1)[0] + ".255"  # assumes a /24 network
    name = cfg.get("client_name", "ClaudeMCP")

    print('Look at the TV and choose "Allow" with your remote...')
    tv = SamsungTVWS(host=host, port=8002, token_file=str(TOKEN), name=name, timeout=60)
    tv.send_key("KEY_VOLUP")
    tv.send_key("KEY_VOLDOWN")

    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"Paired. Wrote {CONFIG.name} and {TOKEN.name}.")
    if not cfg["mac"]:
        print("No MAC address reported, so power-on won't work. Add \"mac\" to "
              "tv_config.json from Settings > Support > About This TV.")


if __name__ == "__main__":
    main()
