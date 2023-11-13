export interface Organisme {
    id_organisme: string;
    nom_organisme: string;
    uuid_organisme: string;
  }

export interface OrganismeComplet {
  id_organisme: string;
  nom_organisme: string;
  uuid_organisme: string;
  rns: [{
    principal: boolean;
    rn: {
      area_code: string;
      area_name: string;
    }
  }]
}

export interface MultiSelectReservesOption {
  id: string;
  name: string;
}