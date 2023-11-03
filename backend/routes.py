from flask import Flask, request, Response, render_template, redirect, Blueprint, jsonify
import requests
import json

bp = Blueprint('routes', __name__)
from app import ma, app
from flask_mail import Mail, Message

from models import Bib_Organismes, CorRoleToken

from pypnusershub import routes as fnauth

from flask_login import login_required

mail = Mail(app)

@bp.route('/organismes', methods=['GET'])
@fnauth.check_auth(1)
# @login_required
def getUsers():
    # test = request.cookies["token"]

    organismes = Bib_Organismes.query.filter(Bib_Organismes.id_organisme.notin_(['-1','1','2'])).order_by(Bib_Organismes.nom_organisme).all()
    
    schema = OrganismeSchema(many=True)
    organObj = schema.dump(organismes)

    return jsonify(organObj)

class OrganismeSchema(ma.SQLAlchemyAutoSchema) :
    class Meta :
        model = Bib_Organismes
        load_instance = True

s = requests.Session()

@bp.route('/inscription', methods=["POST"])
def inscription():
    """
    Ajoute un utilisateur à utilisateurs.temp_user dans la base de UsersHub
    Fait appel à l'API UsersHub
    Code copié depuis GeoNature

    """
    # lignes non nécessaires ici, spécifiques à GeoNature :
    # if not config["ACCOUNT_MANAGEMENT"].get("ENABLE_SIGN_UP", False):
    #     return {"message": "Page introuvable"}, 404

    data = request.get_json()

    if (data["id_organisme"] == '') :
        data["id_organisme"] = None
        orgadb = None
    else :
        organisme = Bib_Organismes.query.filter_by(id_organisme=data["id_organisme"]).first()
        orgadb = organisme.nom_organisme

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
        orgadb=orgadb,
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
            user=data,
            orgadb=orgadb
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
            user=data,
            orgadb=orgadb
            )
            msg = Message(
                subject, 
                sender="si@rnfrance.org", 
                recipients=recipients
            )
            msg.html = msg_html
            mail.send(msg)
        

    return Response(r), r.status_code

@bp.route('/login/recovery', methods=["POST"])
def login_recovery():
    """
    Call UsersHub API to create a TOKEN for a user
    A post_action send an email with the user login and a link to reset its password
    Work only if 'ENABLE_SIGN_UP' is set to True
    """
    data = request.get_json()

    r = s.post(
        url=app.config["API_ENDPOINT"] + "/pypn/register/post_usershub/create_cor_role_token",
        json=data,
    )

    if (r.status_code == 200) :

        user = json.loads(r.text)['role']

        url_password = (
            app.config["URL_INSCRIPTION"] + "/nouveau-mot-de-passe?token=" + json.loads(r.text)['token']
        )

        subject = "Confirmation changement Identifiant / mot de passe"
        template = "email_login_and_new_pass.html"
        recipients = [user["email"]]
        msg_html = render_template(
            template,
            identifiant=user["identifiant"],
            url_password=url_password
        )
        msg = Message(
            subject, 
            sender="si@rnfrance.org", 
            recipients=recipients
        )
        msg.html = msg_html

        mail.send(msg)

        print("message envoyé")

    return Response(r), r.status_code

@bp.route("/after_confirmation", methods=["POST"])
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

@bp.route("/password/new", methods=["PUT"])
def new_password():
    """
    Modifie le mdp d'un utilisateur apres que celui-ci ai demander un renouvelement
    Necessite un token envoyer par mail a l'utilisateur
    """

    data = dict(request.get_json())
    print(data)
    if not data.get("token", None):
        return {"msg": "Erreur serveur"}, 500

    r = s.post(
        url=app.config["API_ENDPOINT"] + "/pypn/register/post_usershub/change_password",
        json=data,
    )

    if r.status_code != 200:
        # comme concerne le password, on explicite pas le message
        return {"msg": "Erreur serveur"}, 500
    return {"msg": "Mot de passe modifié avec succès"}, 200