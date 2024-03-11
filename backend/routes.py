from flask import Flask, request, Response, render_template, redirect, Blueprint, jsonify, g
import requests
import json

bp = Blueprint('routes', __name__)
from app import ma, app, db
from flask_mail import Mail, Message

from models import Bib_Organismes, CorRoleToken, Bib_Reserves, Rnsogs, User, CorRoleRn

from pypnusershub import routes as fnauth

from flask_login import login_required

mail = Mail(app)

@bp.route('/organismes', methods=['GET'])
# @fnauth.check_auth(1)
def getOgs():
    # test = request.cookies["token"]

    organismes = Bib_Organismes.query.filter(Bib_Organismes.id_organisme.notin_(['-1','1','2'])).order_by(Bib_Organismes.nom_organisme).all()
    
    schema = OrganismeSchemaSimple(many=True)
    organObj = schema.dump(organismes)

    return jsonify(organObj)

@bp.route('/organisme/<id>', methods=['GET'])
def getOgById(id):
    # test = request.cookies["token"]

    organisme = Bib_Organismes.query.filter_by(id_organisme = id).first()
    
    schema = OrganismeSchemaComplet(many=False)
    organObj = schema.dump(organisme)

    return jsonify(organObj)

class RnsogsSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Rnsogs
        load_relationships = True
    # organismegestionnaire = ma.Nested(lambda: OrganismeSchema)
    rn = ma.Nested(lambda: ReserveSchema)

class OrganismeSchemaSimple(ma.SQLAlchemyAutoSchema) :
    class Meta :
        model = Bib_Organismes

class OrganismeSchemaComplet(ma.SQLAlchemyAutoSchema) :
    class Meta :
        model = Bib_Organismes
        # load_instance = True
        load_relationships = True

    rns = ma.Nested(lambda: RnsogsSchema, many = True)

s = requests.Session()


@bp.route('/reserves', methods=['GET'])
def getReserves():
    reserves = Bib_Reserves.query.filter(Bib_Reserves.id_type.in_(['5','6','18'])).order_by(Bib_Reserves.area_name).all()

    schema = ReserveSchema(many=True)
    resObj = schema.dump(reserves)

    return jsonify(resObj)

class ReserveSchema(ma.SQLAlchemyAutoSchema) :
    class Meta :
        model = Bib_Reserves
        load_instance = True

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

@bp.route("/send_mail_opnl", methods=["POST"])
def send_mail_opnl():

    data = request.get_json()

    print(data)

    return {"msg": "ok"}

@bp.route("/password/new", methods=["PUT"])
def new_password():
    """
    Modifie le mdp d'un utilisateur apres que celui-ci ai demander un renouvelement
    Necessite un token envoyer par mail a l'utilisateur
    """

    data = dict(request.get_json())

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

@bp.route("/user/<id>", methods=['GET'])
def getUserById(id):
    user = User.query.filter_by(id_role = id).first()
    
    schema = UserSchema(many=False)
    userObj = schema.dump(user)

    return jsonify(userObj)

@bp.route("/role/<id>", methods=['GET'])
def getRoleById(id):
    role = User.query.filter_by(id_role = id).filter_by(groupe=True).first()
    
    schema = RoleSchema(many=False)
    userObj = schema.dump(role)

    return jsonify(userObj)

class UserSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = User
        exclude = ("active", "date_insert", "date_update", "desc_role", "groupe")
        load_relationships = True
    
    groupes = ma.Nested(lambda: RoleSchema, many = True)
    rns = ma.Nested(lambda: RnsUsersSchema, many = True)
    organisme = ma.Nested(lambda: OrganismeSchemaComplet, many = False)

class RoleSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = User
        fields = ("id_role", "nom_role", "desc_role")

class RnsUsersSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = CorRoleRn
        load_relationships = True
    # organismegestionnaire = ma.Nested(lambda: OrganismeSchema)
    rn = ma.Nested(lambda: ReserveSchema)

@bp.route("/role", methods=["PUT"])
@fnauth.check_auth(1)
def update_role():
    """
    Modifie le role de l'utilisateur du token en cours
    """

    init_data = dict(request.get_json())

    print(init_data)
    data = init_data.copy()

    user = g.current_user

    #nettoyage de data pour n'avoir que les attributs existants de User (excluant donc les données réserves)
    attliste = [k for k in data]
    for att in attliste:
        print(att)
        if not getattr(User, att, False):
            data.pop(att)

    # liste des attributs qui ne doivent pas être modifiable par l'user
    black_list_att_update = [
        "active",
        "date_insert",
        "date_update",
        "groupe",
        "id_organisme",
        "organisme",
        "id_role",
        "pass_plus",
        "pn",
        "uuid_role",
    ]

    for key, value in data.items():
        if key not in black_list_att_update:
            setattr(user, key, value)
    
    db.session.merge(user)

    existing_corrolern = CorRoleRn.query.filter_by(role_id=user.id_role).all()
    anciennes_rns = {corrolern.rn_id for corrolern in existing_corrolern}

    nouvelles_rns = {rn['id'] for rn in init_data.get('reserves', [])}

    rns_a_supprimer = anciennes_rns - nouvelles_rns
    rns_a_ajouter = nouvelles_rns - anciennes_rns
    identifiants_communs = anciennes_rns & nouvelles_rns

    nouveaux_referents = {rn['id'] for rn in init_data.get('reserves_referent', [])}

    print(nouveaux_referents)

    for rn in rns_a_supprimer :
        rolern = CorRoleRn.query.filter_by(role_id=user.id_role, rn_id=rn).first()
        if rolern :
            db.session.delete(rolern)

    for rn in rns_a_ajouter :
        rolern = CorRoleRn.query.filter_by(role_id=user.id_role, rn_id=rn).first()
        if not rolern :
            newrolern = CorRoleRn(role_id=user.id_role, rn_id=rn,referent_valid = False)
            if rn in nouveaux_referents :
                newrolern.referent = True
            else :
                newrolern.referent = False
            db.session.add(newrolern)
    
    for rn in identifiants_communs :
        rolern = CorRoleRn.query.filter_by(role_id=user.id_role, rn_id=rn).first()
        if rn in nouveaux_referents :
            if rolern.referent == False :
                rolern.referent = True
        else :
            if rolern.referent == True :
                rolern.referent = False
    
    db.session.commit()

    return user.as_dict()