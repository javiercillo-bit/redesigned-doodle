import requests
import smtplib
from email.mime.text import MIMEText
import os

TODOIST_API_TOKEN = os.environ["TODOIST_API_TOKEN"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL = os.environ["TO_EMAIL"]

HEADERS = {
    "Authorization": f"Bearer {TODOIST_API_TOKEN}"
}

BASE_URL = "https://api.todoist.com/api/v1"


def get_labels():
    url = f"{BASE_URL}/labels"
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        raise Exception(f"Error HTTP labels: {response.text}")

    data = response.json()

    if "results" not in data:
        raise Exception(f"Respuesta inesperada labels: {data}")

    return data["results"]


def get_tasks():
    url = f"{BASE_URL}/tasks"
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        raise Exception(f"Error HTTP tasks: {response.text}")

    data = response.json()

    if "results" not in data:
        raise Exception(f"Respuesta inesperada tasks: {data}")

    return data["results"]


def build_email(tasks, labels):
    label_map = {l["id"]: l["name"] for l in labels}

    lines = []

    for task in tasks:
        content = task["content"]
        task_labels = [label_map.get(lid, "") for lid in task.get("labels", [])]

        label_str = f" [{' ,'.join(task_labels)}]" if task_labels else ""

        lines.append(f"- {content}{label_str}")

    return "\n".join(lines)


def send_email(body):
    msg = MIMEText(body)
    msg["Subject"] = "Todoist Digest"
    msg["From"] = GMAIL_USER
    msg["To"] = TO_EMAIL

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)


def main():
    print("Cargando labels…")
    labels = get_labels()

    print("Obteniendo tareas…")
    tasks = get_tasks()

    print("Construyendo email…")
    body = build_email(tasks, labels)

    print("Enviando email…")
    send_email(body)

    print("Listo.")


if __name__ == "__main__":
    main()
