"""Appels à l'API UsersHub avec authentification admin."""

import json

import requests
from flask import current_app
from sqlalchemy import select

from pypnusershub.db.models import Application
from pypnusershub.env import db


def _usershub_admin_session():
    """
    Ouvre une session requests authentifiée sur UsersHub.
    Retourne (session, None) ou (None, message_erreur).
    """
    id_app_usershub = db.session.scalar(
        select(Application.id_application)
        .where(Application.code_application == "UH")
        .limit(1)
    )
    if not id_app_usershub:
        return None, "Pas d'application UsersHub (code UH) en base"

    session = requests.Session()
    try:
        login = session.post(
            current_app.config["URL_USERSHUB"].rstrip("/") + "/pypn/auth/login",
            json={
                "login": current_app.config["ADMIN_APPLICATION_LOGIN"],
                "password": current_app.config["ADMIN_APPLICATION_PASSWORD"],
                "id_application": id_app_usershub,
            },
            timeout=30,
        )
    except requests.RequestException:
        return None, (
            "Erreur de connexion à UsersHub "
            "(vérifiez URL_USERSHUB et la disponibilité du service)"
        )

    if login.status_code != 200:
        try:
            detail = login.json().get("msg", login.text)
        except Exception:
            detail = login.text
        return None, f"Connexion admin UsersHub impossible : {detail}"

    return session, None


def post_usershub_api(action, data):
    """
    Appelle URL_USERSHUB/api_register/<action> en tant qu'admin application.
    Retourne la réponse requests ou lève une ValueError avec un message utilisateur.
    """
    session, err = _usershub_admin_session()
    if err:
        raise ValueError(err)

    url = (
        current_app.config["URL_USERSHUB"].rstrip("/")
        + "/api_register/"
        + action
    )
    try:
        return session.post(url, json=data, timeout=30)
    except requests.RequestException as exc:
        raise ValueError(f"Erreur de communication avec UsersHub : {exc}") from exc


def usershub_response_tuple(response):
    """Convertit une réponse requests en tuple Flask (body, status)."""
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        try:
            return json.dumps(response.json()), response.status_code
        except Exception:
            pass
    return response.text, response.status_code
