"""
DupliManager — Notification Service
Healthchecks ping + optional SMTP email report after backup completion.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage
from typing import Any, Dict, Optional

from server_py.utils.config_store import settings as settings_config
from server_py.utils.logger import get_logger

logger = get_logger("Notifications")


def _safe_get(d: Any, *keys: str, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _normalize_notifications_cfg() -> Dict[str, Any]:
    settings_data = settings_config.read() or {}
    n = settings_data.get("notifications") or {}
    # Backward compatible defaults
    hc = n.get("healthchecks") or {}
    mail = n.get("email") or {}
    return {
        "healthchecks": {
            "enabled": bool(hc.get("enabled", False)),
            "url": str(hc.get("url") or "").strip(),
            "successKeyword": str(hc.get("successKeyword") or "success").strip() or "success",
            "sendLog": bool(hc.get("sendLog", True)),
            "timeoutSeconds": int(hc.get("timeoutSeconds") or 10),
        },
        "email": {
            "enabled": bool(mail.get("enabled", False)),
            "smtpHost": str(mail.get("smtpHost") or "").strip(),
            "smtpPort": int(mail.get("smtpPort") or 587),
            "smtpUsername": str(mail.get("smtpUsername") or "").strip(),
            "smtpPassword": str(mail.get("smtpPassword") or "").strip(),
            "smtpStartTls": bool(mail.get("smtpStartTls", True)),
            "from": str(mail.get("from") or "").strip(),
            "to": str(mail.get("to") or "").strip(),
            "subjectPrefix": str(mail.get("subjectPrefix") or "[DupliManager]").strip() or "[DupliManager]",
            "sendLog": bool(mail.get("sendLog", True)),
        },
    }


def _merge_repo_notification_overrides(global_cfg: Dict[str, Any], repo_cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = {
        "healthchecks": dict((global_cfg or {}).get("healthchecks") or {}),
        "email": dict((global_cfg or {}).get("email") or {}),
    }
    # La activación se decide SOLO por backup. La configuración global aporta
    # transporte/valores por defecto (URL/SMTP/etc.), no habilita envíos.
    merged["healthchecks"]["enabled"] = False
    merged["email"]["enabled"] = False
    rr = dict(repo_cfg or {})
    rr_hc = dict(rr.get("healthchecks") or {})
    rr_mail = dict(rr.get("email") or {})

    # Per-backup healthchecks: URL/toggle/palabra/sendLog
    if "enabled" in rr_hc:
        merged["healthchecks"]["enabled"] = bool(rr_hc.get("enabled"))
    if rr_hc.get("url"):
        merged["healthchecks"]["url"] = str(rr_hc.get("url") or "").strip()
    if "successKeyword" in rr_hc and str(rr_hc.get("successKeyword") or "").strip():
        merged["healthchecks"]["successKeyword"] = str(rr_hc.get("successKeyword") or "").strip()
    if "sendLog" in rr_hc:
        merged["healthchecks"]["sendLog"] = bool(rr_hc.get("sendLog"))

    # Per-backup email: destinatario/toggle/prefijo/sendLog (SMTP queda global)
    if "enabled" in rr_mail:
        merged["email"]["enabled"] = bool(rr_mail.get("enabled"))
    if rr_mail.get("to"):
        merged["email"]["to"] = str(rr_mail.get("to") or "").strip()
    if "subjectPrefix" in rr_mail and str(rr_mail.get("subjectPrefix") or "").strip():
        merged["email"]["subjectPrefix"] = str(rr_mail.get("subjectPrefix") or "").strip()
    if "sendLog" in rr_mail:
        merged["email"]["sendLog"] = bool(rr_mail.get("sendLog"))

    return merged


def _build_backup_report_text(
    payload: Dict[str, Any],
    *,
    include_log: bool,
    max_log_chars: int,
    signal_keyword: Optional[str] = None,
) -> str:
    repo_name = payload.get("repoName") or "—"
    snapshot_id = payload.get("snapshotId") or "—"
    trigger = payload.get("trigger") or "manual"
    source = payload.get("sourcePath") or "—"
    target = payload.get("targetLabel") or payload.get("targetUrl") or "—"
    finished_at = payload.get("finishedAt") or "—"
    duration = payload.get("durationSeconds")
    summary = payload.get("backupSummary") or {}

    first_line = str(signal_keyword or "").strip()
    lines = [
        first_line if first_line else "signal",
        f"Backup: {repo_name}",
        f"Backup ID (Snapshot ID): {snapshot_id}",
        f"Trigger: {trigger}",
        f"Origen: {source}",
        f"Destino: {target}",
        f"Finalizado: {finished_at}",
    ]
    if duration is not None:
        lines.append(f"Duración (s): {duration}")

    if isinstance(summary, dict) and summary:
        if summary.get("ok"):
            if summary.get("createdRevision") is not None:
                lines.append(f"Revisión creada: #{summary.get('createdRevision')}")
            if summary.get("previousRevision") is not None:
                lines.append(f"Revisión anterior: #{summary.get('previousRevision')}")
            if summary.get("fileCount") is not None:
                lines.append(f"Ficheros en snapshot: {summary.get('fileCount')}")
            lines.append(
                f"Cambios: nuevos={summary.get('new', 0)} cambiados={summary.get('changed', 0)} eliminados={summary.get('deleted', 0)}"
            )
        elif summary.get("message"):
            lines.append(f"Resumen: {summary.get('message')}")

    if include_log:
        raw_log = str(payload.get("backupLog") or "").strip()
        if raw_log:
            if len(raw_log) > max_log_chars:
                raw_log = raw_log[-max_log_chars:]
                lines.append(f"(Log truncado a últimos {max_log_chars} caracteres)")
            lines.append("")
            lines.append("=== LOG BACKUP ===")
            lines.append(raw_log)

    return "\n".join(lines)


def _sanitize_text_for_keyword(raw: str, keyword: str) -> str:
    """
    Evita falsos positivos de Healthchecks cuando el keyword configurado no es 'success'.
    Elimina menciones de 'success' generadas por textos internos/labels para que no disparen
    la clasificación por accidente.
    """
    text = str(raw or "")
    kw = str(keyword or "").strip().lower()
    if kw == "success":
        return text
    # Solo sanitizamos la palabra 'success'; conservamos el resto del mensaje.
    return text.replace("success", "signal").replace("Success", "Signal").replace("SUCCESS", "SIGNAL")


def _send_healthchecks_success_sync(cfg: Dict[str, Any], body: str) -> None:
    url = str(cfg.get("url") or "").strip()
    if not url:
        return
    timeout = int(cfg.get("timeoutSeconds") or 10)
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        code = getattr(resp, "status", None) or resp.getcode()
        logger.info("[Notify] Healthchecks ping OK code=%s url=%s", code, url)


def _send_email_success_sync(cfg: Dict[str, Any], subject: str, body: str) -> None:
    host = str(cfg.get("smtpHost") or "").strip()
    port = int(cfg.get("smtpPort") or 587)
    user = str(cfg.get("smtpUsername") or "").strip()
    password = str(cfg.get("smtpPassword") or "").strip()
    from_addr = str(cfg.get("from") or "").strip()
    to_addr = str(cfg.get("to") or "").strip()
    if not (host and from_addr and to_addr):
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.ehlo()
        if cfg.get("smtpStartTls", True):
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
    logger.info("[Notify] Email enviado OK to=%s host=%s", to_addr, host)


async def notify_backup_success(payload: Dict[str, Any]) -> None:
    """
    Envía notificaciones post-backup exitoso. Nunca debe romper el flujo principal.
    """
    try:
        cfg = _normalize_notifications_cfg()
        cfg = _merge_repo_notification_overrides(cfg, payload.get("repoNotifications"))
        hc_cfg = cfg.get("healthchecks") or {}
        mail_cfg = cfg.get("email") or {}

        if not hc_cfg.get("enabled") and not mail_cfg.get("enabled"):
            return

        healthchecks_body = _build_backup_report_text(
            payload,
            include_log=bool(hc_cfg.get("sendLog", True)),
            max_log_chars=32000,
            signal_keyword=str(hc_cfg.get("successKeyword") or "success").strip() or "success",
        )
        keyword = str(hc_cfg.get("successKeyword") or "success").strip() or "success"
        healthchecks_body = _sanitize_text_for_keyword(healthchecks_body, keyword)

        email_body = _build_backup_report_text(
            payload,
            include_log=bool(mail_cfg.get("sendLog", True)),
            max_log_chars=180000,
            signal_keyword=keyword,
        )
        email_body = _sanitize_text_for_keyword(email_body, keyword)
        subject_prefix = str(mail_cfg.get("subjectPrefix") or "[DupliManager]").strip() or "[DupliManager]"
        subject_keyword = keyword or "success"
        subject = f"{subject_prefix} {subject_keyword} · Backup OK · {payload.get('repoName') or payload.get('snapshotId') or 'backup'}"

        tasks = []
        if hc_cfg.get("enabled") and hc_cfg.get("url"):
            tasks.append(asyncio.to_thread(_send_healthchecks_success_sync, hc_cfg, healthchecks_body))
        if mail_cfg.get("enabled") and mail_cfg.get("smtpHost") and mail_cfg.get("to"):
            tasks.append(asyncio.to_thread(_send_email_success_sync, mail_cfg, subject, email_body))

        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                logger.warning("[Notify] Error enviando notificación de backup: %s", res)
    except Exception:
        logger.exception("[Notify] Error inesperado en notify_backup_success")


async def test_backup_notifications(payload: Dict[str, Any], repo_notifications: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Prueba real de notificaciones (Healthchecks y/o Email) usando la misma ruta de envío
    que se usa tras un backup correcto. No lanza excepción global; devuelve resultados.
    """
    results: Dict[str, Any] = {"ok": True, "channels": {}}
    try:
        cfg = _normalize_notifications_cfg()
        cfg = _merge_repo_notification_overrides(cfg, repo_notifications)
        hc_cfg = cfg.get("healthchecks") or {}
        mail_cfg = cfg.get("email") or {}

        keyword = str(hc_cfg.get("successKeyword") or "success").strip() or "success"
        test_payload = dict(payload or {})
        test_payload.setdefault("repoName", "Prueba notificación")
        test_payload.setdefault("snapshotId", "test-backup-id")
        test_payload.setdefault("trigger", "manual")
        test_payload.setdefault("sourcePath", "—")
        test_payload.setdefault("targetLabel", "—")
        test_payload.setdefault("finishedAt", "—")
        test_payload.setdefault("durationSeconds", 0)
        test_payload.setdefault("backupSummary", {"ok": True, "message": "Prueba manual de notificaciones"})
        test_payload.setdefault("backupLog", "Prueba manual de notificaciones desde DupliManager.")

        hc_body = _build_backup_report_text(
            test_payload,
            include_log=bool(hc_cfg.get("sendLog", True)),
            max_log_chars=32000,
            signal_keyword=str(hc_cfg.get("successKeyword") or "success").strip() or "success",
        )
        hc_body = _sanitize_text_for_keyword(hc_body, keyword)

        email_body = _build_backup_report_text(
            test_payload,
            include_log=bool(mail_cfg.get("sendLog", True)),
            max_log_chars=180000,
            signal_keyword=keyword,
        )
        email_body = _sanitize_text_for_keyword(email_body, keyword)
        subject_prefix = str(mail_cfg.get("subjectPrefix") or "[DupliManager]").strip() or "[DupliManager]"
        subject = f"{subject_prefix} {keyword} · Prueba notificación · {test_payload.get('repoName') or test_payload.get('snapshotId') or 'backup'}"

        tasks = []
        task_names = []

        if hc_cfg.get("enabled") and hc_cfg.get("url"):
            task_names.append("healthchecks")
            tasks.append(asyncio.to_thread(_send_healthchecks_success_sync, hc_cfg, hc_body))
        elif hc_cfg.get("enabled"):
            results["channels"]["healthchecks"] = {"ok": False, "error": "URL Healthchecks no configurada"}
        else:
            results["channels"]["healthchecks"] = {"ok": False, "skipped": True, "reason": "Desactivado"}

        if mail_cfg.get("enabled") and mail_cfg.get("smtpHost") and mail_cfg.get("to"):
            task_names.append("email")
            tasks.append(asyncio.to_thread(_send_email_success_sync, mail_cfg, subject, email_body))
        elif mail_cfg.get("enabled"):
            results["channels"]["email"] = {
                "ok": False,
                "error": "Falta SMTP global o email destino para enviar prueba",
            }
        else:
            results["channels"]["email"] = {"ok": False, "skipped": True, "reason": "Desactivado"}

        if not tasks:
            results["ok"] = False
            results["detail"] = "No hay canales configurados/activos para probar"
            return results

        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        for name, res in zip(task_names, task_results):
            if isinstance(res, Exception):
                results["channels"][name] = {"ok": False, "error": str(res)}
                results["ok"] = False
            else:
                results["channels"][name] = {"ok": True}

        if not results["ok"]:
            results["detail"] = "Una o más pruebas de notificación fallaron"
        return results
    except Exception as ex:
        logger.exception("[Notify] Error inesperado en test_backup_notifications")
        return {"ok": False, "detail": str(ex), "channels": results.get("channels", {})}
