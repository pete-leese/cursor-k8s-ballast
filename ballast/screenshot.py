"""Capture evidence screenshots (ArgoCD, Prometheus) for RCA attachments."""

from __future__ import annotations

import base64
import logging
import os
import subprocess
from typing import Any

from .argocd_evidence import argocd_ui_url
from .argocd_snapshot import argocd_snapshot_document
from .prometheus_evidence import prometheus_alerts_url
from .prometheus_snapshot import prometheus_snapshot_document

log = logging.getLogger(__name__)


def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _launch_chromium(playwright_sync: Any):
    """Launch headless Chromium; prefer full browser over headless-shell."""
    # Headless-shell path resolution is brittle across arch/sandbox caches.
    os.environ.setdefault("PLAYWRIGHT_CHROMIUM_USE_HEADLESS_SHELL", "0")
    return playwright_sync.chromium.launch(headless=True)


def _argocd_looks_like_login(page: Any) -> bool:
    url = (page.url or "").lower()
    if "/login" in url:
        return True
    return page.locator('input[type="password"]').count() > 0


def _argocd_app_ready(page: Any) -> bool:
    text = (page.locator("body").inner_text() or "").lower()
    if "permission denied" in text or "sign in" in text:
        return False
    if page.locator(".application-details, .application-status-panel").count():
        return True
    # Tree / details chrome after a successful deep link.
    return "application details" in text and "sync status" in text


def argocd_admin_password() -> str | None:
    if pw := os.environ.get("ARGOCD_PASSWORD"):
        return pw
    try:
        encoded = subprocess.check_output(
            [
                "kubectl",
                "-n",
                "argocd",
                "get",
                "secret",
                "argocd-initial-admin-secret",
                "-o",
                "jsonpath={.data.password}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return base64.b64decode(encoded).decode()
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return None


def _png_from_html(html: str, *, width: int = 720, height: int = 520) -> bytes | None:
    if not _playwright_available():
        return None
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_content(html, wait_until="load")
            png = page.screenshot(type="png", full_page=True)
            browser.close()
            return png
    except Exception as exc:
        log.debug("HTML snapshot screenshot failed: %s", exc)
        return None


def _png_from_url(url: str, *, width: int = 1280, height: int = 900) -> bytes | None:
    if not _playwright_available():
        return None
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(1200)
            png = page.screenshot(type="png", full_page=False)
            browser.close()
            return png
    except Exception as exc:
        log.debug("URL screenshot failed for %s: %s", url, exc)
        return None


def capture_live_argocd_ui(service: str) -> bytes | None:
    """Screenshot the real ArgoCD application page (requires port-forward + kubectl)."""
    password = argocd_admin_password()
    if not password or not _playwright_available():
        return None

    url = argocd_ui_url(service)
    port = os.environ.get("ARGOCD_PORT", "8080")
    login_url = os.environ.get("ARGOCD_LOGIN_URL") or f"https://localhost:{port}/login"
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            context = browser.new_context(
                ignore_https_errors=True,
                viewport={"width": 1400, "height": 900},
            )
            page = context.new_page()
            # Authenticate via /login first — deep links redirect to login with a
            # splash ("Let's get stuff deployed!") before the form is ready, and
            # the old project-scoped URL looked like a blank permission error.
            page.goto(login_url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_selector('input[type="password"]', timeout=15_000)
            page.locator('input[name="username"], #username').first.fill("admin")
            page.locator('input[type="password"]').first.fill(password)
            page.locator('button[type="submit"]').first.click()
            page.wait_for_timeout(1500)
            if _argocd_looks_like_login(page):
                log.warning("ArgoCD login did not succeed (still on login form)")
                browser.close()
                return None

            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(2500)
            if not _argocd_app_ready(page):
                log.warning(
                    "ArgoCD app page not ready after login (url=%s); refusing login/error shot",
                    page.url,
                )
                browser.close()
                return None

            panel = page.locator(
                ".application-details, .application-status-panel, "
                ".pods, [class*='ApplicationDetails']"
            ).first
            if panel.count():
                png = panel.screenshot(type="png")
            else:
                png = page.screenshot(type="png", full_page=False)
            browser.close()
            return png
    except Exception as exc:
        log.warning("Live ArgoCD screenshot failed: %s", exc)
        return None


def capture_argocd_snapshot_png(argo: dict[str, Any], service: str) -> bytes | None:
    html = argocd_snapshot_document(argo, service)
    return _png_from_html(html)


def capture_argocd_evidence_png(argo: Any, service: str) -> bytes | None:
    mode = os.environ.get("BALLAST_ARGOCD_SCREENSHOT", "auto").lower()
    if mode == "off":
        return None

    argo_dict = argo.model_dump() if hasattr(argo, "model_dump") else dict(argo)

    if mode in ("auto", "live"):
        png = capture_live_argocd_ui(service)
        if png:
            return png

    if mode in ("auto", "snapshot"):
        return capture_argocd_snapshot_png(argo_dict, service)

    return None


def capture_live_prometheus_alerts() -> bytes | None:
    """Screenshot Prometheus /alerts?state=firing (requires port-forward)."""
    return _png_from_url(prometheus_alerts_url(state="firing"))


def capture_prometheus_snapshot_png(
    alert: Any,
    *,
    firing_alerts: list[dict[str, Any]] | None = None,
) -> bytes | None:
    html = prometheus_snapshot_document(alert, firing_alerts=firing_alerts)
    return _png_from_html(html, width=800, height=560)


def capture_prometheus_evidence_png(
    alert: Any,
    *,
    firing_alerts: list[dict[str, Any]] | None = None,
) -> bytes | None:
    """Capture Prometheus alerts PNG. Mode: auto | live | snapshot | off."""
    mode = os.environ.get("BALLAST_PROMETHEUS_SCREENSHOT", "auto").lower()
    if mode == "off":
        return None

    if mode in ("auto", "live"):
        png = capture_live_prometheus_alerts()
        if png:
            return png

    if mode in ("auto", "snapshot"):
        return capture_prometheus_snapshot_png(alert, firing_alerts=firing_alerts)

    return None


def grafana_dashboard_url(service: str | None = None) -> str:
    """Deep link to the Ballast RCA Grafana dashboard (local port-forward by default)."""
    custom = os.environ.get("GRAFANA_DASHBOARD_URL", "").rstrip("/")
    if custom:
        if service and "var-container=" not in custom and "var-pod=" not in custom:
            sep = "&" if "?" in custom else "?"
            return f"{custom}{sep}var-namespace=demo&var-container={service}"
        return custom
    base = os.environ.get("GRAFANA_URL", "http://localhost:3000").rstrip("/")
    uid = os.environ.get("GRAFANA_DASHBOARD_UID", "ballast-rca")
    # kiosk hides chrome for cleaner evidence screenshots.
    params = [
        "orgId=1",
        "from=now-30m",
        "to=now",
        "refresh=15s",
        "kiosk",
        "var-namespace=demo",
    ]
    if service:
        params.append(f"var-container={service}")
    else:
        params.append("var-container=ingest")
    return f"{base}/d/{uid}?{'&'.join(params)}"


def capture_live_grafana_dashboard(service: str | None = None) -> bytes | None:
    """Screenshot a Grafana dashboard (requires port-forward + optional token)."""
    if not _playwright_available():
        return None
    url = grafana_dashboard_url(service)
    token = os.environ.get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "")
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            context_kwargs: dict[str, Any] = {
                "viewport": {"width": 1400, "height": 900},
            }
            if token:
                context_kwargs["extra_http_headers"] = {
                    "Authorization": f"Bearer {token}"
                }
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=25_000)
            # Anonymous Grafana may show a login form — try default admin if present.
            if "login" in page.url.lower():
                user = os.environ.get("GRAFANA_USER", "admin")
                password = os.environ.get("GRAFANA_PASSWORD", "prom-operator")
                page.locator('input[name="user"]').first.fill(user)
                page.locator('input[name="password"]').first.fill(password)
                page.locator('button[type="submit"]').first.click()
                page.wait_for_load_state("networkidle", timeout=20_000)
                page.goto(url, wait_until="networkidle", timeout=25_000)
            page.wait_for_timeout(1500)
            png = page.screenshot(type="png", full_page=False)
            browser.close()
            return png
    except Exception as exc:
        log.warning("Live Grafana screenshot failed: %s", exc)
        return None


def capture_grafana_evidence_png(service: str | None = None) -> bytes | None:
    """Capture Grafana dashboard PNG. Mode: auto | live | off (default auto)."""
    mode = os.environ.get("BALLAST_GRAFANA_SCREENSHOT", "auto").lower()
    if mode == "off":
        return None
    if mode in ("auto", "live"):
        return capture_live_grafana_dashboard(service)
    return None
