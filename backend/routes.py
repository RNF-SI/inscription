from flask import Blueprint, jsonify

bp = Blueprint('routes', __name__)
from app import ma

from models import Bib_Organismes

@bp.route('/organismes', methods=['GET'])
def getUsers():
    organismes = Bib_Organismes.query.filter(Bib_Organismes.id_organisme.notin_(['-1','1','2'])).order_by(Bib_Organismes.nom_organisme).all()
    
    schema = OrganismeSchema(many=True)
    organObj = schema.dump(organismes)

    return jsonify(organObj)

class OrganismeSchema(ma.SQLAlchemyAutoSchema) :
    class Meta :
        model = Bib_Organismes
        load_instance = True