from app import db
from sqlalchemy.dialects.postgresql import JSONB

class Bib_Organismes(db.Model):

    __tablename__ = "bib_organismes"
    __table_args__ = {"schema": "utilisateurs", "extend_existing": True}

    id_organisme = db.Column(db.Integer, primary_key=True)
    uuid_organisme = db.Column(db.Unicode)
    nom_organisme = db.Column(db.Unicode)
    # adresse_organisme = db.Column(db.Unicode)
    # cp_organisme = db.Column(db.Unicode)
    # ville_organisme = db.Column(db.Unicode)
    # tel_organisme = db.Column(db.Unicode)
    # fax_organisme = db.Column(db.Unicode)
    # email_organisme = db.Column(db.Unicode)
    # url_organisme = db.Column(db.Unicode)
    # url_logo = db.Column(db.Unicode)
    # id_parent = db.Column(db.Integer)

class TempUser(db.Model):
    
    __tablename__ = "temp_users"
    __table_args__ = {"schema": "utilisateurs", "extend_existing": True}

    id_temp_user = db.Column(db.Integer, primary_key=True)
    token_role = db.Column(db.Unicode)
    organisme = db.Column(db.Unicode)
    id_application = db.Column(db.Integer)
    confirmation_url = db.Column(db.Unicode)
    groupe = db.Column(db.Boolean)
    identifiant = db.Column(db.Unicode)
    nom_role = db.Column(db.Unicode)
    prenom_role = db.Column(db.Unicode)
    desc_role = db.Column(db.Unicode)
    password = db.Column(db.Unicode)
    pass_md5 = db.Column(db.Unicode)
    email = db.Column(db.Unicode)    
    id_organisme = db.Column(db.Integer)
    remarques = db.Column(db.Unicode)
    champs_addi = db.Column(JSONB)
    date_insert = db.Column(db.DateTime)
    date_update = db.Column(db.DateTime)