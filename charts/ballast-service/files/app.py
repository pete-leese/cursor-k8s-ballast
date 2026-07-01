# ballast-service: allocate a fixed resident-memory ballast at startup, then
# serve health + Prometheus metrics. The startup allocation is what makes the
# service sensitive to resources.limits.memory: too low a limit OOM-kills the
# container here, before it ever becomes ready -> CrashLoopBackOff.
import http.server
import os
import socketserver
import time

SERVICE = os.environ.get("SERVICE_NAME", "service")
VERSION = os.environ.get("SERVICE_VERSION", "0.1.0")
PORT = int(os.environ.get("PORT", "8080"))
BALLAST_MB = int(os.environ.get("BALLAST_MB", "40"))

print(f"[{SERVICE}] allocating {BALLAST_MB}MiB ballast...", flush=True)
_ballast = bytearray(BALLAST_MB * 1024 * 1024)
# Touch every page so the memory is actually resident (counts against the cgroup
# memory limit); a lazy allocation would not trigger the OOM kill.
for _i in range(0, len(_ballast), 4096):
    _ballast[_i] = 1
START = time.time()
print(f"[{SERVICE}] ballast resident; serving on :{PORT}", flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def _w(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if self.path in ("/healthz", "/readyz"):
            self._w(200, "ok\n")
        elif self.path == "/metrics":
            self._w(200,
                "# HELP ballast_up 1 if the service is serving\n"
                "# TYPE ballast_up gauge\n"
                f'ballast_up{{service="{SERVICE}",version="{VERSION}"}} 1\n'
                "# HELP ballast_allocated_bytes resident ballast bytes\n"
                "# TYPE ballast_allocated_bytes gauge\n"
                f'ballast_allocated_bytes{{service="{SERVICE}"}} {len(_ballast)}\n'
                "# HELP ballast_uptime_seconds seconds since startup\n"
                "# TYPE ballast_uptime_seconds gauge\n"
                f'ballast_uptime_seconds{{service="{SERVICE}"}} {time.time() - START:.0f}\n')
        else:
            self._w(200, f"{SERVICE} v{VERSION} ok\n")

    def log_message(self, *a):
        pass


with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as httpd:
    httpd.serve_forever()
