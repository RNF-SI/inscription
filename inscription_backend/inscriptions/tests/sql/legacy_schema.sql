-- Réplique minimale de la base historique, pour les tests d'intégration de
-- l'écriture miroir (inscriptions/tests/test_legacy_integration.py).
--
-- Ne contient que ce dans quoi la plateforme écrit, plus les triggers de
-- production qui en dépendent : c'est justement leur comportement qu'il faut
-- vérifier, en particulier after_insert_user_function() qui peuple cor_role_rn
-- à l'INSERT de t_roles.
--
-- Sources : le DDL du module UsersHub (backend/dependancies/.../migrations/data/
-- utilisateurs.sql) pour le schéma `utilisateurs`, et les triggers fournis par
-- l'exploitant pour `complement_rnf`. Les schémas `ref_geo` et `complement_rnf`
-- n'ont pas de DDL dans le dépôt : ils sont reconstitués depuis les modèles
-- SQLAlchemy et les requêtes de lecture, et peuvent différer de la production
-- sur les types exacts.

CREATE SCHEMA IF NOT EXISTS utilisateurs;
CREATE SCHEMA IF NOT EXISTS utilisateurs_saisie;
CREATE SCHEMA IF NOT EXISTS utilisateurs_sinp;
CREATE SCHEMA IF NOT EXISTS complement_rnf;
CREATE SCHEMA IF NOT EXISTS ref_geo;

-- --- Horodatage : posé par trigger, jamais par l'application -----------------

CREATE OR REPLACE FUNCTION utilisateurs.modify_date_insert() RETURNS trigger AS $$
BEGIN
    NEW.date_insert := now();
    NEW.date_update := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION utilisateurs.modify_date_update() RETURNS trigger AS $$
BEGIN
    NEW.date_update := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- --- Schéma utilisateurs -----------------------------------------------------

CREATE TABLE utilisateurs.bib_organismes (
    id_organisme     serial PRIMARY KEY,
    uuid_organisme   uuid NOT NULL DEFAULT gen_random_uuid(),
    nom_organisme    varchar(500) NOT NULL
);

CREATE TABLE utilisateurs.t_roles (
    groupe         boolean DEFAULT false NOT NULL,
    id_role        serial PRIMARY KEY,
    uuid_role      uuid NOT NULL DEFAULT gen_random_uuid(),
    identifiant    varchar(100),
    nom_role       varchar(50),
    prenom_role    varchar(50),
    desc_role      text,
    "pass"         varchar(100),
    pass_plus      text,
    email          varchar(250),
    id_organisme   integer REFERENCES utilisateurs.bib_organismes (id_organisme),
    remarques      text,
    active         boolean DEFAULT true,
    champs_addi    jsonb,
    date_insert    timestamp without time zone,
    date_update    timestamp without time zone
);

CREATE TRIGGER tri_modify_date_insert_t_roles BEFORE INSERT ON utilisateurs.t_roles
    FOR EACH ROW EXECUTE FUNCTION utilisateurs.modify_date_insert();
CREATE TRIGGER tri_modify_date_update_t_roles BEFORE UPDATE ON utilisateurs.t_roles
    FOR EACH ROW EXECUTE FUNCTION utilisateurs.modify_date_update();

CREATE TABLE utilisateurs.t_applications (
    id_application   serial PRIMARY KEY,
    code_application varchar(20) NOT NULL,
    nom_application  varchar(50) NOT NULL
);

CREATE TABLE utilisateurs.t_profils (
    id_profil   serial PRIMARY KEY,
    code_profil varchar(20),
    nom_profil  varchar(255)
);

CREATE TABLE utilisateurs.cor_role_app_profil (
    id_role                  integer NOT NULL REFERENCES utilisateurs.t_roles (id_role) ON DELETE CASCADE,
    id_application           integer NOT NULL REFERENCES utilisateurs.t_applications (id_application) ON DELETE CASCADE,
    id_profil                integer NOT NULL REFERENCES utilisateurs.t_profils (id_profil) ON DELETE CASCADE,
    is_default_group_for_app boolean NOT NULL DEFAULT false,
    PRIMARY KEY (id_role, id_application, id_profil)
);

CREATE TABLE utilisateurs.cor_roles (
    id_role_groupe      integer NOT NULL REFERENCES utilisateurs.t_roles (id_role) ON DELETE CASCADE,
    id_role_utilisateur integer NOT NULL REFERENCES utilisateurs.t_roles (id_role) ON DELETE CASCADE,
    PRIMARY KEY (id_role_groupe, id_role_utilisateur)
);

-- Profils livrés par le DDL d'origine ; 1 = Lecteur, celui qu'accordait UsersHub.
INSERT INTO utilisateurs.t_profils (id_profil, code_profil, nom_profil) VALUES
    (0, '0', 'Aucun'), (1, '1', 'Lecteur'), (2, '2', 'Rédacteur'),
    (3, '3', 'Référent'), (4, '4', 'Modérateur'), (5, '5', 'Validateur'),
    (6, '6', 'Administrateur');

-- Application « inscription » (LEGACY_INSCRIPTION_APP_ID).
INSERT INTO utilisateurs.t_applications (id_application, code_application, nom_application)
    VALUES (6, 'INS', 'Inscription');

-- --- Référentiel géographique ------------------------------------------------

CREATE TABLE ref_geo.l_areas (
    id_area   serial PRIMARY KEY,
    id_type   integer,
    area_code varchar(25) UNIQUE,
    area_name varchar(250)
);

-- --- complement_rnf ----------------------------------------------------------
-- rn_id porte le CODE textuel de la réserve, pas un identifiant numérique.

CREATE TABLE complement_rnf.cor_role_rn (
    role_id        integer NOT NULL REFERENCES utilisateurs.t_roles (id_role) ON DELETE CASCADE,
    rn_id          text NOT NULL REFERENCES ref_geo.l_areas (area_code),
    referent       boolean,
    referent_valid boolean,
    PRIMARY KEY (role_id, rn_id)
);

CREATE TABLE complement_rnf.site_internet_utilisateurs (
    id_role     integer PRIMARY KEY,
    uuid_role   uuid,
    identifiant varchar(100),
    nom_role    varchar(50),
    prenom_role varchar(50),
    password    text,
    email       varchar(250),
    fonction    text
);

-- Copies alimentées par le trigger de diffusion.
CREATE TABLE utilisateurs_saisie.t_roles (LIKE utilisateurs.t_roles INCLUDING DEFAULTS);
CREATE TABLE utilisateurs_sinp.t_roles  (LIKE utilisateurs.t_roles INCLUDING DEFAULTS);

-- --- Triggers de production --------------------------------------------------
-- Reproduits à l'identique : ce sont eux qui déduisent cor_role_rn du champs_addi
-- et diffusent les comptes vers les bases satellites.

CREATE OR REPLACE FUNCTION public.after_insert_user_function() RETURNS trigger AS $$
BEGIN
    IF (TG_OP = 'INSERT') THEN
        INSERT INTO complement_rnf.cor_role_rn (role_id, rn_id, referent)
        SELECT NEW.id_role, value->>'id',
            COALESCE(new.champs_addi->'reserves_referent' @> jsonb_build_array(jsonb_build_object('id', value->>'id'))::jsonb, false)
        FROM jsonb_array_elements(CASE WHEN jsonb_typeof(new.champs_addi->'reserves') = 'array' THEN new.champs_addi->'reserves' ELSE '[]' END) AS value
        WHERE jsonb_typeof(new.champs_addi->'reserves') = 'array';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tri_after_insert_user AFTER INSERT ON utilisateurs.t_roles
    FOR EACH ROW EXECUTE FUNCTION public.after_insert_user_function();

CREATE OR REPLACE FUNCTION complement_rnf.user_change() RETURNS trigger AS $$
BEGIN
    IF (TG_OP = 'INSERT') THEN
        IF (new.groupe is not true AND new.active is true AND new.pass_plus is not null) THEN
            INSERT INTO complement_rnf.site_internet_utilisateurs
                (id_role, uuid_role, identifiant, nom_role, prenom_role, password, email, fonction)
            VALUES (new.id_role, new.uuid_role, new.identifiant, new.nom_role,
                    new.prenom_role, new.pass_plus, new.email, new.remarques);
        END IF;
    ELSIF (TG_OP = 'UPDATE') THEN
        IF (new.groupe is not true AND new.active is true AND old.active is true AND new.pass_plus is not null) THEN
            UPDATE complement_rnf.site_internet_utilisateurs
               SET identifiant = new.identifiant, nom_role = new.nom_role,
                   prenom_role = new.prenom_role, password = new.pass_plus,
                   email = new.email, fonction = new.remarques
             WHERE id_role = old.id_role;
        END IF;
    ELSIF (TG_OP = 'DELETE') THEN
        DELETE FROM complement_rnf.site_internet_utilisateurs WHERE id_role = old.id_role;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tri_user_change AFTER INSERT OR UPDATE OR DELETE ON utilisateurs.t_roles
    FOR EACH ROW EXECUTE FUNCTION complement_rnf.user_change();

CREATE OR REPLACE FUNCTION complement_rnf.sync_table_t_roles() RETURNS trigger AS $$
BEGIN
    IF (TG_OP = 'DELETE') THEN
        DELETE FROM utilisateurs_saisie.t_roles WHERE id_role = OLD.id_role;
        DELETE FROM utilisateurs_sinp.t_roles   WHERE id_role = OLD.id_role;
        RETURN OLD;
    ELSIF (TG_OP = 'UPDATE') THEN
        UPDATE utilisateurs_saisie.t_roles SET
            identifiant = NEW.identifiant, nom_role = NEW.nom_role, prenom_role = NEW.prenom_role,
            "pass" = NEW."pass", pass_plus = NEW.pass_plus, email = NEW.email,
            id_organisme = NEW.id_organisme, remarques = NEW.remarques, active = NEW.active,
            champs_addi = NEW.champs_addi, date_update = NEW.date_update
        WHERE id_role = NEW.id_role;
        UPDATE utilisateurs_sinp.t_roles SET
            identifiant = NEW.identifiant, nom_role = NEW.nom_role, prenom_role = NEW.prenom_role,
            "pass" = NEW."pass", pass_plus = NEW.pass_plus, email = NEW.email,
            id_organisme = NEW.id_organisme, remarques = NEW.remarques, active = NEW.active,
            champs_addi = NEW.champs_addi, date_update = NEW.date_update
        WHERE id_role = NEW.id_role;
        RETURN NEW;
    ELSIF (TG_OP = 'INSERT') THEN
        INSERT INTO utilisateurs_saisie.t_roles
            (groupe, id_role, uuid_role, identifiant, nom_role, prenom_role, desc_role,
             "pass", pass_plus, email, id_organisme, remarques, active, champs_addi,
             date_insert, date_update)
        VALUES (NEW.groupe, NEW.id_role, NEW.uuid_role, NEW.identifiant, NEW.nom_role,
                NEW.prenom_role, NEW.desc_role, NEW."pass", NEW.pass_plus, NEW.email,
                NEW.id_organisme, NEW.remarques, NEW.active, NEW.champs_addi,
                NEW.date_insert, NEW.date_update);
        INSERT INTO utilisateurs_sinp.t_roles
            (groupe, id_role, uuid_role, identifiant, nom_role, prenom_role, desc_role,
             "pass", pass_plus, email, id_organisme, remarques, active, champs_addi,
             date_insert, date_update)
        VALUES (NEW.groupe, NEW.id_role, NEW.uuid_role, NEW.identifiant, NEW.nom_role,
                NEW.prenom_role, NEW.desc_role, NEW."pass", NEW.pass_plus, NEW.email,
                NEW.id_organisme, NEW.remarques, NEW.active, NEW.champs_addi,
                NEW.date_insert, NEW.date_update);
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tri_sync_table_t_roles AFTER INSERT OR UPDATE OR DELETE ON utilisateurs.t_roles
    FOR EACH ROW EXECUTE FUNCTION complement_rnf.sync_table_t_roles();

-- --- Jeu d'essai -------------------------------------------------------------

INSERT INTO utilisateurs.bib_organismes (id_organisme, nom_organisme) VALUES (1, 'RNF test');
INSERT INTO ref_geo.l_areas (id_type, area_code, area_name) VALUES
    (5, 'RNN41', 'Grand Lieu'), (5, 'RNN99', 'Camargue');
