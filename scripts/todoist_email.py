import os
import smtplib
import sys
import json
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
CACHE_FILE    = "label_cache.json"


# ── API helpers ────────────────────────────────────────────────────────────────

def fetch_labels_map() -> dict[str, str]:
    """Obtiene labels desde API"""
    resp = requests.get(
        f"{TODOIST_BASE}/labels",
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, list):
        raise ValueError(f"Respuesta inesperada labels: {data}")

    return {label["name"]: label["id"] for label in data}


def load_labels_map() -> dict[str, str]:
    """Carga cache o consulta API si no existe"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            print("Cache corrupto, regenerando…")

    labels = fetch_labels_map()
    save_labels_map(labels)
    return labels


def save_labels_map(labels: dict[str, str]):
    with open(CACHE_FILE, "w") as f:
        json.dump(labels, f)


def get_tasks_by_label_id(label_id: str) -> list[dict]:
    resp = requests.get(
        f"{TODOIST_BASE}/tasks",
        headers=HEADERS,
        params={"label_id": label_id},
        timeout=15,
    )
    resp.raise_for_status()

    data = resp.json()

    if not isinstance(data, list):
        raise ValueError(f"Respuesta inesperada tasks: {data}")

    return data


# ── Parsing ────────────────────────────────────────────────────────────────────

def parse_due_date(task: dict):
    due = task.get("due")
    if not due:
        return None
    raw = due.get("date", "")
    return date.fromisoformat(raw[:10]) if raw else None


def parse_deadline_date(task: dict):
    dl = task.get("deadline")
    if not dl:
        return None
    raw = dl.get("date", "")
    return date.fromisoformat(raw[:10]) if raw else None


# ── Render ─────────────────────────────────────────────────────────────────────

def format_task_line(task: dict, date_fn=parse_due_date) -> str:
    content  = task.get("content", "(sin título)")
    d        = date_fn(task)
    date_str = f" ({d.strftime('%d %b')})" if d else ""
    priority = task.get("priority", 1)
    dot      = {4: "🔴", 3: "🟠", 2: "🔵", 1: ""}.get(priority, "")
    url      = f"https://app.todoist.com/app/task/{task['id']}"

    return f"{dot} {content}{date_str} → {url}"


# ── Email ──────────────────────────────────────────────────────────────────────

def send_email(subject: str, body: str):
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, TO_EMAIL, msg.as_string())


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("Cargando labels…")
    labels_map = load_labels_map()

    def get_label_id(name: str) -> str:
        if name not in labels_map:
            print(f"Label '{name}' no encontrado en cache. Refrescando…")
            labels_map.update(fetch_labels_map())
            save_labels_map(labels_map)

        if name not in labels_map:
            raise RuntimeError(f"Label inexistente en Todoist: {name}")

        return labels_map[name]

    hoy_id    = get_label_id(LABEL_HOY)
    semana_id = get_label_id(LABEL_ESTA_SEMANA)
    dl_id     = get_label_id(LABEL_DEADLINE)

    print("Obteniendo tareas…")
    tasks_hoy    = get_tasks_by_label_id(hoy_id)
    tasks_semana = get_tasks_by_label_id(semana_id)
    tasks_dl_raw = get_tasks_by_label_id(dl_id)

    today  = date.today()
    cutoff = today + timedelta(days=DEADLINE_DAYS)

    tasks_deadline = [
        t for t in tasks_dl_raw
        if (d := parse_deadline_date(t)) is None or (today <= d <= cutoff)
    ]

    body = f"""
Hoy: {len(tasks_hoy)}
Esta semana: {len(tasks_semana)}
Deadline: {len(tasks_deadline)}

--- HOY ---
{chr(10).join(format_task_line(t) for t in tasks_hoy)}

--- SEMANA ---
{chr(10).join(format_task_line(t) for t in tasks_semana)}

--- DEADLINE ---
{chr(10).join(format_task_line(t, parse_deadline_date) for t in tasks_deadline)}
"""

    subject = f"Todoist {today.strftime('%d %b %Y')}"

    print("Enviando correo…")
    send_email(subject, body)
    print("OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
