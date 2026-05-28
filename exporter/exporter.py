#!/usr/bin/env python3

import datetime
import json
import os
import re
import socket
import struct
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote


DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
ADHOC_CONTAINER = os.environ.get("ADHOC_CONTAINER", "psppeeps-adhoc-server")
EXPORTER_HOST = os.environ.get("EXPORTER_HOST", "0.0.0.0")
EXPORTER_PORT = int(os.environ.get("EXPORTER_PORT", "27314"))
LOG_TAIL = int(os.environ.get("LOG_TAIL", "5000"))


PRODUCTS = {
    "ULUS10410": {"game": "psp1", "region": "us", "title": "Phantasy Star Portable US"},
    "ULES01218": {"game": "psp1", "region": "eu_au", "title": "Phantasy Star Portable EU/AU"},
    "ULJM05309": {"game": "psp1", "region": "jp", "title": "Phantasy Star Portable JP"},
    "ULJM08023": {"game": "psp1", "region": "jp_best", "title": "Phantasy Star Portable JP PSP the Best"},

    "ULUS10529": {"game": "psp2", "region": "us", "title": "Phantasy Star Portable 2 US"},
    "ULES01439": {"game": "psp2", "region": "eu_au", "title": "Phantasy Star Portable 2 EU/AU"},
    "ULJM05493": {"game": "psp2", "region": "jp", "title": "Phantasy Star Portable 2 JP"},
    "NPJH50043": {"game": "psp2", "region": "jp_psn", "title": "Phantasy Star Portable 2 JP PSN"},
    "ULJM08030": {"game": "psp2", "region": "jp_best", "title": "Phantasy Star Portable 2 JP PSP the Best"},

    "ULJM05732": {"game": "psp2i", "region": "jp", "title": "Phantasy Star Portable 2 Infinity JP"},
    "NPJH50332": {"game": "psp2i", "region": "jp_psn", "title": "Phantasy Star Portable 2 Infinity JP PSN"},
}


START_RE = re.compile(
    r"^(?P<name>.+) \(MAC: (?P<mac>[0-9A-Fa-f:]+) - IP: (?P<ip>[^)]+)\) started playing (?P<product>[A-Z0-9]{9})\."
)
STOP_RE = re.compile(
    r"^(?P<name>.+) \(MAC: (?P<mac>[0-9A-Fa-f:]+) - IP: (?P<ip>[^)]+)\) stopped playing (?P<product>[A-Z0-9]{9})\."
)
JOIN_RE = re.compile(
    r"^(?P<name>.+) \(MAC: (?P<mac>[0-9A-Fa-f:]+) - IP: (?P<ip>[^)]+)\) joined (?P<product>[A-Z0-9]{9}) group (?P<group>.*)\."
)
LEFT_RE = re.compile(
    r"^(?P<name>.+) \(MAC: (?P<mac>[0-9A-Fa-f:]+) - IP: (?P<ip>[^)]+)\) left (?P<product>[A-Z0-9]{9}) group (?P<group>.*)\."
)
REJECT_RE = re.compile(
    r"^Rejected non-Phantasy-Star-Portable product code (?P<product>[A-Z0-9]{9}) from (?P<ip>[0-9.]+)\."
)


class ExporterState:
    def __init__(self):
        self.connected = {}
        self.group_members = defaultdict(set)
        self.logins_total = defaultdict(int)
        self.rejected_total = defaultdict(int)
        self.seen_lines = set()
        self.seen_order = deque(maxlen=20000)
        self.container_started_at = None
        self.last_scrape_success = 0
        self.last_scrape_error = ""

    def reset_live_state(self):
        self.connected.clear()
        self.group_members.clear()
        self.seen_lines.clear()
        self.seen_order.clear()


STATE = ExporterState()


def decode_chunked(body):
    out = bytearray()
    pos = 0

    while True:
        idx = body.find(b"\r\n", pos)
        if idx == -1:
            return bytes(out) if out else body

        size_text = body[pos:idx].split(b";", 1)[0].strip()
        try:
            size = int(size_text, 16)
        except ValueError:
            return body

        pos = idx + 2
        if size == 0:
            return bytes(out)

        out.extend(body[pos:pos + size])
        pos += size + 2


def demux_docker_stream(body):
    chunks = []
    pos = 0

    while pos + 8 <= len(body):
        stream_type = body[pos]
        reserved = body[pos + 1:pos + 4]
        size = struct.unpack(">I", body[pos + 4:pos + 8])[0]

        if stream_type not in (0, 1, 2) or reserved != b"\x00\x00\x00":
            break

        start = pos + 8
        end = start + size
        if end > len(body):
            break

        chunks.append(body[start:end])
        pos = end

    if chunks:
        return b"".join(chunks)

    return body


def docker_get(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(DOCKER_SOCKET)
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: docker\r\n"
            f"User-Agent: psppeeps-adhoc-exporter\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode("ascii")
        sock.sendall(req)

        data = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data.extend(chunk)
    finally:
        sock.close()

    raw = bytes(data)
    header_blob, sep, body = raw.partition(b"\r\n\r\n")
    if not sep:
        raise RuntimeError("invalid Docker API response")

    header_lines = header_blob.decode("iso-8859-1", errors="replace").split("\r\n")
    status_line = header_lines[0]
    parts = status_line.split()
    if len(parts) < 2:
        raise RuntimeError(f"invalid Docker API status: {status_line}")

    status = int(parts[1])
    headers = {}
    for line in header_lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip().lower()

    if headers.get("transfer-encoding") == "chunked":
        body = decode_chunked(body)

    if status >= 400:
        raise RuntimeError(f"Docker API returned HTTP {status}: {body[:300]!r}")

    return body


def parse_docker_time(value):
    if not value:
        return None

    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    if "." in s:
        head, rest = s.split(".", 1)
        frac = ""
        tz = ""

        for idx, ch in enumerate(rest):
            if ch.isdigit():
                frac += ch
            else:
                tz = rest[idx:]
                break

        frac = frac[:6].ljust(6, "0")
        s = f"{head}.{frac}{tz}"

    return datetime.datetime.fromisoformat(s).timestamp()


def product_meta(product):
    return PRODUCTS.get(product, {
        "game": "unknown",
        "region": "unknown",
        "title": "Unknown PSP title",
    })


def label_escape(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def labels_for_product(product):
    meta = product_meta(product)
    return (
        f'product_id="{label_escape(product)}",'
        f'game="{label_escape(meta["game"])}",'
        f'region="{label_escape(meta["region"])}",'
        f'title="{label_escape(meta["title"])}"'
    )


def read_container_info():
    body = docker_get(f"/containers/{quote(ADHOC_CONTAINER, safe='')}/json")
    info = json.loads(body.decode("utf-8"))
    state = info.get("State", {})
    running = bool(state.get("Running"))
    started_at = state.get("StartedAt")
    started_epoch = parse_docker_time(started_at)
    return running, started_at, started_epoch


def read_container_logs_since(started_epoch):
    since = int(started_epoch or (time.time() - 3600))
    path = (
        f"/containers/{quote(ADHOC_CONTAINER, safe='')}/logs"
        f"?stdout=1&stderr=1&timestamps=1&since={since}&tail={LOG_TAIL}"
    )
    body = docker_get(path)
    body = demux_docker_stream(body)
    return body.decode("utf-8", errors="replace").splitlines()


def remember_line(line_id):
    if line_id in STATE.seen_lines:
        return False

    if len(STATE.seen_order) == STATE.seen_order.maxlen:
        old = STATE.seen_order.popleft()
        STATE.seen_lines.discard(old)

    STATE.seen_order.append(line_id)
    STATE.seen_lines.add(line_id)
    return True


def strip_docker_timestamp(line):
    if len(line) > 30 and line[:4].isdigit() and " " in line:
        return line.split(" ", 1)[1]
    return line


def process_log_line(line):
    line_id = line
    if not remember_line(line_id):
        return

    msg = strip_docker_timestamp(line)

    m = START_RE.match(msg)
    if m:
        mac = m.group("mac").upper()
        product = m.group("product")
        STATE.connected[mac] = product
        STATE.logins_total[product] += 1
        return

    m = STOP_RE.match(msg)
    if m:
        mac = m.group("mac").upper()
        STATE.connected.pop(mac, None)

        for members in STATE.group_members.values():
            members.discard(mac)
        return

    m = JOIN_RE.match(msg)
    if m:
        mac = m.group("mac").upper()
        product = m.group("product")
        group = m.group("group")
        STATE.connected[mac] = product
        STATE.group_members[(product, group)].add(mac)
        return

    m = LEFT_RE.match(msg)
    if m:
        mac = m.group("mac").upper()
        product = m.group("product")
        group = m.group("group")
        STATE.group_members[(product, group)].discard(mac)
        return

    m = REJECT_RE.match(msg)
    if m:
        product = m.group("product")
        STATE.rejected_total[product] += 1
        return


def refresh_state():
    try:
        running, started_at, started_epoch = read_container_info()

        if started_at != STATE.container_started_at:
            STATE.container_started_at = started_at
            STATE.reset_live_state()

        if running:
            for line in read_container_logs_since(started_epoch):
                process_log_line(line)

        STATE.last_scrape_success = 1
        STATE.last_scrape_error = ""
        return running
    except Exception as e:
        STATE.last_scrape_success = 0
        STATE.last_scrape_error = str(e)
        return False


def render_metrics():
    running = refresh_state()

    connected_by_product = defaultdict(int)
    for product in STATE.connected.values():
        connected_by_product[product] += 1

    active_groups_by_product = defaultdict(int)
    active_groups = 0
    players_in_groups_by_product = defaultdict(set)

    adhoc_lobbies_by_product = defaultdict(int)
    players_in_lobbies_by_product = defaultdict(set)

    for (product, group), members in STATE.group_members.items():
        if not members:
            continue

        # PSP/PPSSPP logs use an empty-looking group name when the player is
        # in the adhoc lobby / party-staging state, e.g.:
        #   joined ULUS10410 group .
        # Non-empty generated names are treated as formed party/game groups.
        if group == "":
            adhoc_lobbies_by_product[product] += 1
            for mac in members:
                players_in_lobbies_by_product[product].add(mac)
            continue

        active_groups += 1
        active_groups_by_product[product] += 1

        for mac in members:
            players_in_groups_by_product[product].add(mac)

    players_in_groups = sum(len(members) for members in players_in_groups_by_product.values())
    players_in_lobbies = sum(len(members) for members in players_in_lobbies_by_product.values())
    adhoc_lobbies = sum(adhoc_lobbies_by_product.values())

    out = []

    out.append("# HELP psppeeps_adhoc_server_up Whether the PPSSPP adhoc server container is running.")
    out.append("# TYPE psppeeps_adhoc_server_up gauge")
    out.append(f"psppeeps_adhoc_server_up {1 if running else 0}")

    out.append("# HELP psppeeps_adhoc_exporter_last_scrape_success Whether the exporter successfully read Docker state/logs.")
    out.append("# TYPE psppeeps_adhoc_exporter_last_scrape_success gauge")
    out.append(f"psppeeps_adhoc_exporter_last_scrape_success {STATE.last_scrape_success}")

    out.append("# HELP psppeeps_adhoc_connected_clients Current connected adhoc clients.")
    out.append("# TYPE psppeeps_adhoc_connected_clients gauge")
    out.append(f"psppeeps_adhoc_connected_clients {len(STATE.connected)}")

    out.append("# HELP psppeeps_adhoc_connected_clients_by_product Current connected adhoc clients by PSP product ID.")
    out.append("# TYPE psppeeps_adhoc_connected_clients_by_product gauge")
    for product, count in sorted(connected_by_product.items()):
        out.append(f"psppeeps_adhoc_connected_clients_by_product{{{labels_for_product(product)}}} {count}")

    out.append("# HELP psppeeps_adhoc_active_groups Current active adhoc groups.")
    out.append("# TYPE psppeeps_adhoc_active_groups gauge")
    out.append(f"psppeeps_adhoc_active_groups {active_groups}")

    out.append("# HELP psppeeps_adhoc_active_groups_by_product Current active adhoc groups by PSP product ID.")
    out.append("# TYPE psppeeps_adhoc_active_groups_by_product gauge")
    for product, count in sorted(active_groups_by_product.items()):
        out.append(f"psppeeps_adhoc_active_groups_by_product{{{labels_for_product(product)}}} {count}")

    out.append("# HELP psppeeps_adhoc_players_in_groups Current adhoc clients inside active PSP groups.")
    out.append("# TYPE psppeeps_adhoc_players_in_groups gauge")
    out.append(f"psppeeps_adhoc_players_in_groups {players_in_groups}")

    out.append("# HELP psppeeps_adhoc_players_in_groups_by_product Current adhoc clients inside active PSP groups by PSP product ID.")
    out.append("# TYPE psppeeps_adhoc_players_in_groups_by_product gauge")
    for product, members in sorted(players_in_groups_by_product.items()):
        out.append(f"psppeeps_adhoc_players_in_groups_by_product{{{labels_for_product(product)}}} {len(members)}")

    out.append("# HELP psppeeps_adhoc_lobbies Current adhoc lobby/staging groups.")
    out.append("# TYPE psppeeps_adhoc_lobbies gauge")
    out.append(f"psppeeps_adhoc_lobbies {adhoc_lobbies}")

    out.append("# HELP psppeeps_adhoc_lobbies_by_product Current adhoc lobby/staging groups by PSP product ID.")
    out.append("# TYPE psppeeps_adhoc_lobbies_by_product gauge")
    for product, count in sorted(adhoc_lobbies_by_product.items()):
        out.append(f"psppeeps_adhoc_lobbies_by_product{{{labels_for_product(product)}}} {count}")

    out.append("# HELP psppeeps_adhoc_players_in_lobbies Current adhoc clients inside PSP lobby/staging state.")
    out.append("# TYPE psppeeps_adhoc_players_in_lobbies gauge")
    out.append(f"psppeeps_adhoc_players_in_lobbies {players_in_lobbies}")

    out.append("# HELP psppeeps_adhoc_players_in_lobbies_by_product Current adhoc clients inside PSP lobby/staging state by PSP product ID.")
    out.append("# TYPE psppeeps_adhoc_players_in_lobbies_by_product gauge")
    for product, members in sorted(players_in_lobbies_by_product.items()):
        out.append(f"psppeeps_adhoc_players_in_lobbies_by_product{{{labels_for_product(product)}}} {len(members)}")

    out.append("# HELP psppeeps_adhoc_logins_total Accepted adhoc login events observed by exporter.")
    out.append("# TYPE psppeeps_adhoc_logins_total counter")
    for product, count in sorted(STATE.logins_total.items()):
        out.append(f"psppeeps_adhoc_logins_total{{{labels_for_product(product)}}} {count}")

    out.append("# HELP psppeeps_adhoc_rejected_logins_total Rejected adhoc login events observed by exporter.")
    out.append("# TYPE psppeeps_adhoc_rejected_logins_total counter")
    for product, count in sorted(STATE.rejected_total.items()):
        out.append(f"psppeeps_adhoc_rejected_logins_total{{{labels_for_product(product)},reason=\"not_allowed\"}} {count}")

    out.append("# HELP psppeeps_adhoc_product_info Known Phantasy Star Portable product IDs.")
    out.append("# TYPE psppeeps_adhoc_product_info gauge")
    for product in sorted(PRODUCTS):
        out.append(f"psppeeps_adhoc_product_info{{{labels_for_product(product)}}} 1")

    out.append("# HELP psppeeps_adhoc_exporter_info Exporter info.")
    out.append("# TYPE psppeeps_adhoc_exporter_info gauge")
    out.append(f'psppeeps_adhoc_exporter_info{{container="{label_escape(ADHOC_CONTAINER)}"}} 1')

    if STATE.last_scrape_error:
        out.append("# HELP psppeeps_adhoc_exporter_error_info Last exporter error.")
        out.append("# TYPE psppeeps_adhoc_exporter_error_info gauge")
        out.append(f'psppeeps_adhoc_exporter_error_info{{error="{label_escape(STATE.last_scrape_error)}"}} 1')

    return "\n".join(out) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return

        body = render_metrics().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def main():
    server = HTTPServer((EXPORTER_HOST, EXPORTER_PORT), MetricsHandler)
    print(f"psppeeps adhoc exporter listening on {EXPORTER_HOST}:{EXPORTER_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
