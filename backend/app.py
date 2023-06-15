import requests
import json

from flask import Flask, request, Response, render_template, redirect
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow

from importlib import import_module

from config import Config

# from models import Bib_Organismes




app = Flask(__name__)
app.config.from_object(Config)

# blueprint relié au module usershub-authentification
from pypnusershub import routes_register
app.register_blueprint(routes_register.bp, url_prefix='/pypn/register')

cors = CORS(app, resources={ r'/*': {'origins': "*"}})

db = SQLAlchemy(app) 
ma = Marshmallow(app)

import routes
app.register_blueprint(routes.bp)




