import requests
import json

from flask import Flask, request, Response, render_template, redirect
from flask_cors import CORS
from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow

from importlib import import_module

from config import Config




app = Flask(__name__)
app.config.from_object(Config)

# blueprint relié au module usershub-authentification
from pypnusershub import routes_register
app.register_blueprint(routes_register.bp, url_prefix='/pypn/register')

cors = CORS(app, resources={ r'/*': {'origins': "*"}})

mail = Mail(app)

db = SQLAlchemy(app) 
ma = Marshmallow(app)

import routes
app.register_blueprint(routes.bp)

s = requests.Session()

@app.route('/inscription', methods=["POST"])
def inscription():
    print("entré", flush=True)
    """
    Ajoute un utilisateur à utilisateurs.temp_user dans la base de UsersHub
    Fait appel à l'API UsersHub
    Code copié depuis GeoNature

    """
    # lignes non nécessaires ici, spécifiques à GeoNature :
    # if not config["ACCOUNT_MANAGEMENT"].get("ENABLE_SIGN_UP", False):
    #     return {"message": "Page introuvable"}, 404

    data = request.get_json()

    print(data)
    # ajout des valeurs non présentes dans le form
    data["id_application"] = 6
    data["groupe"] = False
    data["confirmation_url"] = app.config["API_ENDPOINT"] + "/after_confirmation"

    r = s.post(
        url=app.config["API_ENDPOINT"] + "/pypn/register/post_usershub/create_temp_user",
        json=data,
    )

    if (r.status_code == 200) :

        if (data['champs_addi']['ancrage']) :
            subject = "Demande de compte pour la BAO Ancrage"
            template = "email_ancrage.html"
            recipients = [app.config["MAIL_ANCRAGE"]]
            msg_html = render_template(
            template,
            user=data
            )
            msg = Message(
                subject, 
                sender="si@rnfrance.org", 
                recipients=recipients
            )
            msg.html = msg_html
            mail.send(msg)

        if (data['champs_addi']['psdrf']) :
            subject = "Demande de compte pour le module PSDRF"
            template = "email_psdrf.html"
            recipients = [app.config["MAIL_PSDRF"]]
            msg_html = render_template(
            template,
            user=data
            )
            msg = Message(
                subject, 
                sender="si@rnfrance.org", 
                recipients=recipients
            )
            msg.html = msg_html
            mail.send(msg)
        

    return Response(r), r.status_code

@app.route("/confirmation", methods=["GET"])
def confirmation():
    """
        Validate a account after a demande (this action is triggered by the link in the email)
        Create a personnal JDD as post_action if the parameter AUTO_DATASET_CREATION is set to True
        Fait appel à l'API UsersHub
    """
    # test des droits
    # if not config["ACCOUNT_MANAGEMENT"].get("ENABLE_SIGN_UP", False):
    #     return {"message": "Page introuvable"}, 404

    token = request.args.get("token", None)
    if token is None:
        return {"message": "Token introuvable"}, 404

    data = {"token": token, "id_application": 6}

    r = s.post(
        url=app.config["API_ENDPOINT"] + "/pypn/register/post_usershub/valid_temp_user", json=data,
    )

    if r.status_code != 200:
        return Response(r), r.status_code

    return redirect(app.config["URL_APPLICATION"], code=302)

@app.route("/after_confirmation", methods=["POST"])
def after_confirmation():
    data = dict(request.get_json())
    type_action = "valid_temp_user"
    after_confirmation_fn = function_dict.get(type_action, None)
    result = after_confirmation_fn(data)
    if result != 0 and result["msg"] != "ok":
        msg = f"Problem in GeoNature API after confirmation {type_action} : {result['msg']}"
        return json.dumps({"msg": msg}), 500
    else:
        return json.dumps(result)

# for blueprint_path, url_prefix in [
#         ("pypnusershub.routes_register:bp", "/pypn/register"),

#     ]:module_name, blueprint_name = blueprint_path.split(":")
# blueprint = getattr(import_module(module_name), blueprint_name)
# app.register_blueprint(blueprint, url_prefix=url_prefix)

