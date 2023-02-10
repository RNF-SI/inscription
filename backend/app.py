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

        subject = "Demande d'inscription au SI"
        template = "email_global.html"
        recipients = ["si@rnfrance.org"]
        msg_html = render_template(
        template,
        user=data,
        additional_fields=[
            {"key": key, "value": value}
            for key, value in (data.get("champs_addi") or {}).items()
        ]
        )
        msg = Message(
            subject, 
            sender="si@rnfrance.org", 
            recipients=recipients
        )
        msg.html = msg_html
        mail.send(msg)

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

@app.route("/after_confirmation", methods=["POST"])
def after_confirmation():

    data = request.get_json()

    subject = "Inscription au SI de RNF confirmée"
    template = "email_confirm_user_validation.html"
    recipients = [data['email']]
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

    return {"msg": "ok"}


