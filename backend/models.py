from app import db
from sqlalchemy.dialects.postgresql import JSONB

class Rnsogs(db.Model):
    
    __tablename__ = 'cor_rn_og'
    __table_args__ = {"schema": "complement_rnf", "extend_existing": True}

    rn_id = db.Column(db.Unicode, db.ForeignKey('ref_geo.l_areas.area_code'), primary_key=True)
    og_uuid = db.Column(db.Unicode, db.ForeignKey('utilisateurs.bib_organismes.uuid_organisme'), primary_key=True)

    rn = db.relationship("Bib_Reserves", back_populates="organismes_gestionnaires")
    organismegestionnaire = db.relationship("Bib_Organismes", back_populates="rns")

    principal = db.Column(db.Boolean)

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

    rns = db.relationship(
        "Rnsogs", back_populates = "organismegestionnaire"
    )


class CorRoleToken(db.Model):

    __tablename__ = "cor_role_token"
    __table_args__ = {"schema": "utilisateurs", "extend_existing": True}

    id_role = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.Unicode)

class Bib_Reserves(db.Model):

    __tablename__ = "l_areas"
    __table_args__ = {"schema": "ref_geo", "extend_existing": True}

    id_area = db.Column(db.Integer, primary_key=True)
    id_type = db.Column(db.Unicode)
    area_name = db.Column(db.Unicode)
    area_code = db.Column(db.Unicode)

    organismes_gestionnaires = db.relationship(
        "Rnsogs", back_populates = "rn"
    )
    