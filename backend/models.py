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

    roles = db.relationship(
        "CorRoleRn", back_populates = "rn"
    )

class CorRoleRn(db.Model):

    __tablename__ = 'cor_role_rn'
    __table_args__ = {"schema": "complement_rnf", "extend_existing": True}

    role_id = db.Column(db.Unicode, db.ForeignKey('utilisateurs.t_roles.id_role'), primary_key=True)
    rn_id = db.Column(db.Unicode, db.ForeignKey('ref_geo.l_areas.area_code'), primary_key=True)

    rn = db.relationship("Bib_Reserves", back_populates="roles")
    role = db.relationship("User", back_populates="rns")

    referent = db.Column(db.Boolean)
    referent_valid = db.Column(db.Boolean)

cor_roles = db.Table(
    "cor_roles",
    db.Column(
        "id_role_utilisateur",
        db.Integer,
        db.ForeignKey("utilisateurs.t_roles.id_role"),
        primary_key=True,
    ),
    db.Column(
        "id_role_groupe",
        db.Integer,
        db.ForeignKey("utilisateurs.t_roles.id_role"),
        primary_key=True,
    ),
    schema="utilisateurs",
    extend_existing=True,
)

class User(db.Model):

    __tablename__ = "t_roles"
    __table_args__ = {"schema": "utilisateurs", "extend_existing": True}
    
    groupe = db.Column(db.Boolean, default=False)
    id_role = db.Column(
        db.Integer,
        primary_key=True,
    )

    # TODO: make that unique ?
    identifiant = db.Column(db.Unicode)
    nom_role = db.Column(db.Unicode)
    prenom_role = db.Column(db.Unicode)
    desc_role = db.Column(db.Unicode)
    # _password = db.Column("pass", db.Unicode)
    # _password_plus = db.Column("pass_plus", db.Unicode)
    email = db.Column(db.Unicode)
    id_organisme = db.Column(db.Integer, db.ForeignKey("utilisateurs.bib_organismes.id_organisme"))
    remarques = db.Column(db.Unicode)
    champs_addi = db.Column(JSONB)
    date_insert = db.Column(db.DateTime)
    date_update = db.Column(db.DateTime)
    active = db.Column(db.Boolean)
    groupes = db.relationship(
        "User",
        lazy="joined",
        secondary=cor_roles,
        primaryjoin="User.id_role == utilisateurs.cor_roles.c.id_role_utilisateur",
        secondaryjoin="User.id_role == utilisateurs.cor_roles.c.id_role_groupe",
        backref=db.backref("members"),
    )

    rns = db.relationship(
        "CorRoleRn", back_populates = "role"
    )
    organisme = db.relationship("Bib_Organismes", foreign_keys=[id_organisme])

