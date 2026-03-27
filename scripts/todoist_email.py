"""
todoist_email.py
Obtiene tareas de Todoist con etiquetas @Hoy, @Esta_semana y @Deadline
(las de @Deadline filtradas por su campo 'deadline.date', próximos 30 días)
y envía un resumen por correo vía SMTP de Gmail.

Usa la Todoist API v1 (la REST v2 está deprecated desde finales de 2025).
La API v1 devuelve respuestas paginadas: {"results": [...], "next_cursor": "..."}

Variables de entorno requeridas:
  TODOIST_API_TOKEN  — token de la API de Todoist
  GMAIL_USER         — tu dirección Gmail (remitente)
  GMAIL_APP_PASSWORD — contraseña de aplicación de Gmail
  TO_EMAIL           — destinatario (puede ser el mismo Gmail)
"""

import os
import smtplib
import sys
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

# ── Configuración ──────────────────────────────────────────────────────────────

TODOIST_API_TOKEN  = os.environ["TODOIST_API_TOKEN"]
GMAIL_USER         = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL           = os.environ["TO_EMAIL"]

TODOIST_BASE = "https://api.todoist.com/api/v1"
HEADERS      = {"Authorization": f"Bearer {TODOIST_API_TOKEN}"}

LABEL_HOY         = "Hoy"
LABEL_ESTA_SEMANA = "Esta_semana"
LABEL_DEADLINE    = "Deadline"

DEADLINE_DAYS = 30


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_tasks_by_label(label: str) -> list[dict]:
    """
    Devuelve todas las tareas activas con una etiqueta dada.
    La API v1 usa paginación con cursor: {"results": [...], "next_cursor": "..."}
    Itera hasta agotar todas las páginas.
    """
    tasks  = []
    cursor = None

    while True:
        params = {"label": label}
        if cursor:
            params["cursor"] = cursor

        resp = requests.get(
            f"{TODOIST_BASE}/tasks",
            headers=HEADERS,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        # La API v1 devuelve {"results": [...], "next_cursor": "..." | null}
        page = data.get("results", data)   # fallback por si cambia la estructura
        if isinstance(page, list):
            tasks.extend(page)
        else:
            # Si por alguna razón sigue siendo lista directa, manejar igual
            tasks.extend(data)
            break

        cursor = data.get("next_cursor")
        if not cursor:
            break

    return tasks


def parse_due_date(task: dict) -> date | None:
    """Extrae la *due date* (fecha programada) de una tarea."""
    due = task.get("due")
    if not due:
        return None
    raw = due.get("date", "")
    return date.fromisoformat(raw[:10]) if raw else None


def parse_deadline_date(task: dict) -> date | None:
    """
    Extrae la *deadline date* de una tarea.
    Todoist distingue 'due' (fecha programada) de 'deadline' (fecha límite real).
    El objeto deadline tiene la forma: {"date": "YYYY-MM-DD", "lang": "es"}
    """
    dl = task.get("deadline")
    if not dl:
        return None
    raw = dl.get("date", "")
    return date.fromisoformat(raw[:10]) if raw else None


def format_task_line(task: dict, date_fn=parse_due_date) -> str:
    """Devuelve una línea HTML representando la tarea."""
    content  = task.get("content", "(sin título)")
    d        = date_fn(task)
    date_str = f" <span style='color:#888;font-size:13px;'>({d.strftime('%d %b')})</span>" if d else ""
    priority = task.get("priority", 1)
    dot      = {4: "🔴", 3: "🟠", 2: "🔵", 1: ""}.get(priority, "")
    url      = f"https://app.todoist.com/app/task/{task['id']}"
    return (
        f"<li style='margin-bottom:6px;'>"
        f"{dot} <a href='{url}' style='color:#1a1a1a;text-decoration:none;'>{content}</a>"
        f"{date_str}</li>"
    )


def build_section(title: str, tasks: list[dict], accent: str,
                  date_fn=parse_due_date) -> str:
    """Construye un bloque HTML para una sección del correo."""
    if not tasks:
        items = "<li style='color:#888;'>Sin tareas</li>"
    else:
        items = "\n".join(format_task_line(t, date_fn=date_fn) for t in tasks)

    return f"""
    <div style='margin-bottom:24px;'>
      <h2 style='font-size:15px;font-weight:600;color:{accent};
                 border-bottom:2px solid {accent};padding-bottom:4px;margin:0 0 10px;'>
        {title}
      </h2>
      <ul style='margin:0;padding-left:18px;font-size:14px;line-height:1.7;'>
        {items}
      </ul>
    </div>
    """


DIAS_ES = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
}
MESES_ES = {
    "January": "enero", "February": "febrero", "March": "marzo",
    "April": "abril", "May": "mayo", "June": "junio",
    "July": "julio", "August": "agosto", "September": "septiembre",
    "October": "octubre", "November": "noviembre", "December": "diciembre",
}


def build_email_html(
    hoy:      list[dict],
    semana:   list[dict],
    deadline: list[dict],
) -> str:
    today = date.today()
    dia   = DIAS_ES[today.strftime("%A")]
    mes   = MESES_ES[today.strftime("%B")]
    today_str = f"{dia}, {today.day:02d} de {mes} de {today.year}"

    sec_hoy    = build_section("📌 Hoy",        hoy,    "#c0392b")
    sec_semana = build_section("📅 Esta semana", semana, "#2980b9")
    sec_deadline = build_section(
        f"⏳ Deadlines — próximos {DEADLINE_DAYS} días",
        sorted(deadline, key=lambda t: parse_deadline_date(t) or date.max),
        "#8e44ad",
        date_fn=parse_deadline_date,
    )

    total = len(hoy) + len(semana) + len(deadline)

    return f"""
    <!DOCTYPE html>
    <html lang='es'>
    <head><meta charset='UTF-8'></head>
    <body style='font-family:sans-serif;background:#f5f5f5;margin:0;padding:20px;'>
      <div style='max-width:560px;margin:auto;background:#fff;
                  border-radius:8px;padding:28px 32px;box-shadow:0 1px 4px rgba(0,0,0,.08);'>

        <p style='font-size:12px;color:#aaa;margin:0 0 4px;text-transform:uppercase;
                  letter-spacing:.05em;'>Resumen diario · Todoist</p>
        <h1 style='font-size:20px;font-weight:700;margin:0 0 20px;color:#111;'>
          {today_str}
        </h1>

        {sec_hoy}
        {sec_semana}
        {sec_deadline}

        <p style='font-size:12px;color:#bbb;margin:24px 0 0;text-align:center;'>
          {total} tarea{'s' if total != 1 else ''} en total · generado automáticamente
        </p>
      </div>
    </body>
    </html>
    """


# ── Envío de correo ────────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    today  = date.today()
    cutoff = today + timedelta(days=DEADLINE_DAYS)

    print("Obteniendo tareas de Todoist…")
    tasks_hoy    = get_tasks_by_label(LABEL_HOY)
    tasks_semana = get_tasks_by_label(LABEL_ESTA_SEMANA)
    tasks_dl_raw = get_tasks_by_label(LABEL_DEADLINE)

    # Filtrar @Deadline por deadline.date (no por due.date)
    tasks_deadline = [
        t for t in tasks_dl_raw
        if (d := parse_deadline_date(t)) is None or (today <= d <= cutoff)
    ]

    print(
        f"  @Hoy: {len(tasks_hoy)} | "
        f"@Esta_semana: {len(tasks_semana)} | "
        f"@Deadline (próx. {DEADLINE_DAYS}d): {len(tasks_deadline)}"
    )

    html    = build_email_html(tasks_hoy, tasks_semana, tasks_deadline)
    subject = f"📋 Todoist · {today.strftime('%d %b %Y')}"

    print(f"Enviando correo a {TO_EMAIL}…")
    send_email(subject, html)
    print("✓ Correo enviado.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
