export class User {
    id_role: string;
    id_organisme: number;
    prenom_role: string;
    nom_role: string;
    identifiant: string;

    constructor(id_role: string, id_organisme: number, prenom_role: string, nom_role: string, identifiant: string) {
        this.id_role = id_role;
        this.id_organisme = id_organisme;
        this.prenom_role = prenom_role;
        this.nom_role = nom_role;
        this.identifiant = identifiant;
    }
}

export interface userRnsObj {
    items: userRns[]
    limit: number
    page: number
    total: number
    total_filtered: number
}

export interface userRns {
    role_id: number
    rn_id: number
    rn_nom: string
    area_x: string
    area_y: string
}

export interface userAppRulesObj {
    items: userAppRules[]
    limit: number
    page: number
    total: number
    total_filtered: number
}

export interface userAppRules {
    unique_id: number,
    id_role: number,
    id_application: number,
    id_droit_max: number
}