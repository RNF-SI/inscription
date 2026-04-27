from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests
from django.conf import settings

logger = logging.getLogger("inscriptions.keycloak")


class KeycloakAdminError(Exception):
    pass


class KeycloakAdminClient:
    """
    Client Admin Keycloak : token client_credentials, ensure_group_path,
    rattachement utilisateur aux groupes, création utilisateur.
    """

    def __init__(self) -> None:
        self.base = settings.KEYCLOAK_BASE_URL.rstrip("/")
        self.realm = settings.KEYCLOAK_REALM
        self.admin_client_id = settings.KEYCLOAK_ADMIN_CLIENT_ID
        self.admin_client_secret = (settings.KEYCLOAK_ADMIN_CLIENT_SECRET or "").strip()
        self._token: Optional[str] = None

    @property
    def _admin_base(self) -> str:
        return f"{self.base}/admin/realms/{self.realm}"

    def _token_url(self) -> str:
        return f"{self.base}/realms/{self.realm}/protocol/openid-connect/token"

    def is_configured(self) -> bool:
        return bool(self.admin_client_secret) or self.admin_client_id == "admin-cli"

    def get_access_token(self) -> str:
        if self._token:
            return self._token
        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self.admin_client_id,
        }
        if self.admin_client_secret:
            data["client_secret"] = self.admin_client_secret
        r = requests.post(self._token_url(), data=data, timeout=30)
        if r.status_code != 200:
            logger.error("Keycloak token error: %s %s", r.status_code, r.text[:500])
            raise KeycloakAdminError("keycloak_token_failed")
        payload = r.json()
        self._token = payload.get("access_token")
        if not self._token:
            raise KeycloakAdminError("keycloak_token_missing")
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_access_token()}", "Content-Type": "application/json"}

    def _get(self, path: str) -> requests.Response:
        return requests.get(f"{self._admin_base}{path}", headers=self._headers(), timeout=30)

    def _post(self, path: str, json: Any | None = None) -> requests.Response:
        return requests.post(f"{self._admin_base}{path}", headers=self._headers(), json=json, timeout=30)

    def _put(self, path: str, json: Any | None = None) -> requests.Response:
        return requests.put(f"{self._admin_base}{path}", headers=self._headers(), json=json, timeout=30)

    def _find_child_group_id(self, parent_id: str, child_name: str) -> str | None:
        children = self.get_subgroups(parent_id)
        found = next(
            (
                c
                for c in children
                if str(c.get("name", "")).strip().lower() == child_name.strip().lower() and c.get("id")
            ),
            None,
        )
        if found:
            return found["id"]

        # Fallback robuste : recherche globale par nom, puis filtrage par chemin.
        parent = self._get(f"/groups/{parent_id}")
        if parent.status_code != 200:
            return None
        parent_path = (parent.json() or {}).get("path") or ""
        if not parent_path:
            return None
        target_path = f"{parent_path}/{child_name}"

        search = self._get(
            f"/groups?search={requests.utils.quote(child_name)}&exact=true&briefRepresentation=false"
        )
        if search.status_code != 200:
            return None
        for g in search.json() or []:
            gid = g.get("id")
            if not gid:
                continue
            path = g.get("path")
            if not path:
                details = self._get(f"/groups/{gid}")
                if details.status_code == 200:
                    path = (details.json() or {}).get("path")
            if path == target_path:
                return gid

        # Dernier fallback fiable: parcourir l'arbre des groupes top-level et matcher le path exact.
        try:
            tops = self.list_top_groups()
        except KeycloakAdminError:
            return None

        def _walk(groups: list[dict]) -> str | None:
            for g in groups or []:
                g_path = g.get("path")
                g_id = g.get("id")
                if g_path == target_path and g_id:
                    return g_id
                nested = g.get("subGroups") or []
                found_id = _walk(nested)
                if found_id:
                    return found_id
            return None

        return _walk(tops)

    def list_top_groups(self) -> list[dict]:
        r = self._get("/groups?briefRepresentation=false")
        if r.status_code != 200:
            raise KeycloakAdminError(f"list_groups:{r.status_code}")
        return r.json() or []

    def get_subgroups(self, parent_id: str) -> list[dict]:
        # Endpoint dédié aux sous-groupes (plus fiable que le champ subGroups de /groups/{id}).
        # On itère par pages pour éviter les réponses tronquées.
        out: list[dict] = []
        first = 0
        page_size = 200
        while True:
            r = self._get(
                f"/groups/{parent_id}/children?first={first}&max={page_size}&briefRepresentation=false"
            )
            if r.status_code != 200:
                # Fallback de compatibilité selon versions Keycloak.
                legacy = self._get(f"/groups/{parent_id}?briefRepresentation=false")
                if legacy.status_code != 200:
                    raise KeycloakAdminError(f"get_group_children:{r.status_code}")
                data = legacy.json() or {}
                return data.get("subGroups") or []

            batch = r.json() or []
            if not isinstance(batch, list):
                break
            out.extend(batch)
            if len(batch) < page_size:
                break
            first += page_size
        return out

    def create_child_group(self, parent_id: str, name: str) -> str:
        r = self._post(f"/groups/{parent_id}/children", json={"name": name})
        if r.status_code == 409:
            # Le groupe existe déjà (course condition / duplication) :
            # on relit avec retries pour gérer la latence d'indexation Keycloak.
            for _ in range(5):
                gid = self._find_child_group_id(parent_id, name)
                if gid:
                    return gid
                time.sleep(0.2)
            raise KeycloakAdminError("create_child_group_conflict_unresolved")
        if r.status_code not in (200, 201):
            logger.error("create_child_group %s: %s", r.status_code, r.text[:500])
            raise KeycloakAdminError(f"create_child_group_failed:{r.status_code}:{r.text[:200]}")
        try:
            j = r.json()
            if isinstance(j, dict) and j.get("id"):
                return j["id"]
        except ValueError:
            pass
        loc = r.headers.get("Location", "")
        gid = loc.rstrip("/").split("/")[-1] if loc else ""
        if not gid:
            raise KeycloakAdminError("create_child_group_no_id")
        return gid

    def create_top_group(self, name: str) -> str:
        r = self._post("/groups", json={"name": name})
        if r.status_code == 409:
            # Déjà présent : on retourne l'id existant.
            for g in self.list_top_groups():
                if g.get("name") == name and g.get("id"):
                    return g["id"]
            raise KeycloakAdminError("create_top_group_conflict_unresolved")
        if r.status_code not in (200, 201):
            raise KeycloakAdminError(f"create_top_group_failed:{r.status_code}:{r.text[:200]}")
        loc = r.headers.get("Location", "")
        return loc.rstrip("/").split("/")[-1]

    def ensure_root(self, root_name: str) -> str:
        for g in self.list_top_groups():
            if g.get("name") == root_name:
                return g["id"]
        return self.create_top_group(root_name)

    def ensure_path_under_root(self, root_name: str, segments: list[str], last_attributes: dict | None = None) -> str:
        """
        Crée la chaîne root/seg1/seg2/... et retourne l'id du groupe feuille.
        last_attributes: attributs Keycloak à fusionner sur le dernier segment uniquement.
        """
        parent_id = self.ensure_root(root_name)
        current_id = parent_id
        for i, seg in enumerate(segments):
            children = self.get_subgroups(current_id)
            found = next((c for c in children if c.get("name") == seg), None)
            if found:
                current_id = found["id"]
            else:
                current_id = self.create_child_group(current_id, seg)
            if i == len(segments) - 1 and last_attributes:
                attrs = {k: [str(v)] for k, v in last_attributes.items() if v is not None}
                r = self._put(f"/groups/{current_id}", json={"name": seg, "attributes": attrs})
                if r.status_code not in (200, 204):
                    logger.warning("group attributes update: %s %s", r.status_code, r.text[:300])
        return current_id

    def ensure_organisme_group(self, slug: str, id_organisme: int, nom_organisme: str, uuid_organisme: str) -> str:
        root = settings.KEYCLOAK_GROUP_ORGANISMES
        return self.ensure_path_under_root(
            root,
            [slug],
            last_attributes={
                "id_organisme": id_organisme,
                "nom_organisme": nom_organisme,
                "uuid_organisme": uuid_organisme or "",
            },
        )

    def ensure_reserve_group(self, code: str) -> str:
        root = settings.KEYCLOAK_GROUP_RESERVES
        return self.ensure_path_under_root(root, [code])

    def ensure_application_group(self, slug: str) -> str:
        root = settings.KEYCLOAK_GROUP_APPLICATIONS
        return self.ensure_path_under_root(root, [slug])

    def user_join_group(self, user_id: str, group_id: str) -> None:
        h = {"Authorization": f"Bearer {self.get_access_token()}"}
        r = requests.put(f"{self._admin_base}/users/{user_id}/groups/{group_id}", headers=h, timeout=30)
        if r.status_code not in (200, 204):
            raise KeycloakAdminError(f"user_join_group:{r.status_code}:{r.text[:200]}")
        # Vérification best-effort: si l'API renvoie la liste des groupes, on confirme l'effet.
        check = requests.get(f"{self._admin_base}/users/{user_id}/groups", headers=h, timeout=30)
        if check.status_code == 200:
            groups = check.json() or []
            in_group = any(g.get("id") == group_id for g in groups if isinstance(g, dict))
            if not in_group:
                raise KeycloakAdminError("user_join_group_not_effective")
        elif check.status_code not in (401, 403):
            logger.warning("user groups check failed: %s %s", check.status_code, check.text[:200])

    def user_leave_group(self, user_id: str, group_id: str) -> None:
        h = {"Authorization": f"Bearer {self.get_access_token()}"}
        r = requests.delete(f"{self._admin_base}/users/{user_id}/groups/{group_id}", headers=h, timeout=30)
        if r.status_code not in (200, 204):
            raise KeycloakAdminError(f"user_leave_group:{r.status_code}:{r.text[:200]}")

    def create_user(
        self,
        username: str,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        temporary_password: bool = True,
    ) -> str:
        body = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": True,
            "emailVerified": False,
            "credentials": [{"type": "password", "value": password, "temporary": temporary_password}],
        }
        r = self._post("/users", json=body)
        if r.status_code not in (200, 201):
            logger.error("create_user %s: %s", r.status_code, r.text[:500])
            raise KeycloakAdminError("create_user_failed")
        loc = r.headers.get("Location", "")
        uid = loc.rstrip("/").split("/")[-1] if loc else ""
        if not uid:
            uid = self.find_user_by_username(username) or ""
        if not uid:
            raise KeycloakAdminError("create_user_no_id")
        return uid

    def find_user_by_username(self, username: str) -> str | None:
        r = self._get(f"/users?username={requests.utils.quote(username)}&exact=true")
        if r.status_code != 200:
            return None
        arr = r.json() or []
        if not arr:
            return None
        return arr[0].get("id")
