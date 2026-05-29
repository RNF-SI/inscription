import os

import requests
import json

from flask import Flask, request, Response, render_template, redirect, current_app, g
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow

from config import Config

# from models import Bib_Organismes

app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy()
ma = Marshmallow()

# Partager db/ma avec pypnusershub (obligatoire en 3.x)
os.environ.setdefault("FLASK_SQLALCHEMY_DB", "app.db")
os.environ.setdefault("FLASK_MARSHMALLOW", "app.ma")

db.init_app(app)
ma.init_app(app)

from pypnusershub.auth.auth_manager import auth_manager
from pypnusershub import routes_register

_DEFAULT_AUTH_PROVIDERS = [
    {
        "module": "pypnusershub.auth.providers.default.LocalProvider",
        "id_provider": "local_provider",
    },
]


def _auth_providers():
    """Liste des fournisseurs d'identité (config optionnelle AUTHENTICATION.PROVIDERS)."""
    return app.config.get("AUTHENTICATION", {}).get("PROVIDERS", _DEFAULT_AUTH_PROVIDERS)


auth_manager.init_app(
    app,
    prefix="/auth",
    providers_declaration=_auth_providers(),
)

# blueprint relié au module usershub-authentification
app.register_blueprint(routes_register.bp, url_prefix="/pypn/register")

# cors = CORS(app, resources={ r'/*': {'origins': "*"}},supports_credentials=True)
CORS(app, supports_credentials=True)

import routes

app.register_blueprint(routes.bp)

# @app.before_request
# def load_current_user():
#     g.current_user = current_user if current_user.is_authenticated else None
#     print(current_user)
#     print("sdfg")
