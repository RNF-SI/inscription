import requests
import json

from flask import Flask, request, Response, render_template, redirect, current_app, g
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow

from importlib import import_module

from config import Config

import flask_login
from flask_login import current_user

from pypnusershub.login_manager import login_manager

# from models import Bib_Organismes

app = Flask(__name__)
app.config.from_object(Config)

# login_manager = flask_login.LoginManager() # importé depuis pypnusershub
login_manager.init_app(app)

# blueprint relié au module usershub-authentification
from pypnusershub import routes_register
app.register_blueprint(routes_register.bp, url_prefix='/pypn/register')

# cors = CORS(app, resources={ r'/*': {'origins': "*"}},supports_credentials=True)
CORS(app, supports_credentials=True)

db = SQLAlchemy(app) 
ma = Marshmallow(app)

import routes
app.register_blueprint(routes.bp)

from pypnusershub.routes import routes
app.register_blueprint(routes, url_prefix='/auth')

# @app.before_request
# def load_current_user():
#     g.current_user = current_user if current_user.is_authenticated else None
#     print(current_user)
#     print("sdfg")