from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests
from django.conf import settings

logger = logging.getLogger("inscriptions.keycloak")


class KeycloakAdminError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail or code
        super().__init__(self.detail)


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
        # Listages de groupes mémorisés le temps de vie du client. L'arborescence est
        # parcourue à chaque ensure_* : sans cela, créer les 289 groupes d'organisme
        # relit 289 fois les ~280 enfants de /organismes, soit un quart d'heure avant
        # que l'import ne traite son premier compte. Les vues instancient un client
        # par requête : la mémorisation y est donc de très courte durée.
        self._groups_cache: dict[str, list[dict]] = {}

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
        r = self._send(requests.post, self._token_url(), data=data)
        if r.status_code != 200:
            logger.error("Keycloak token error: %s %s", r.status_code, r.text[:500])
            raise KeycloakAdminError("keycloak_token_failed")
        payload = r.json()
        self._token = payload.get("access_token")
        if not self._token:
            raise KeycloakAdminError("keycloak_token_missing")
        return self._token

    def reset_token(self) -> None:
        self._token = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_access_token()}", "Content-Type": "application/json"}

    @staticmethod
    def _send(method, url: str, **kwargs) -> requests.Response:
        """Enveloppe les erreurs réseau : sans cela, une ConnectionError/Timeout
        remonte telle quelle et échappe aux `except KeycloakAdminError` des appelants
        (dégradation gracieuse de /api/me/, des groupes, etc.) → 500."""
        timeout = getattr(settings, "KEYCLOAK_HTTP_TIMEOUT", 10)
        try:
            return method(url, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            logger.warning("Keycloak injoignable (%s): %s", url, exc)
            raise KeycloakAdminError("keycloak_unreachable", str(exc)) from exc

    def _request(self, method, path: str, **kwargs) -> requests.Response:
        """Appelle l'Admin API, en redemandant un jeton une fois sur 401.

        Le jeton est mis en cache sans suivi d'expiration, et Keycloak peut par
        ailleurs renvoyer un jeton déjà périmé lorsqu'il réutilise une session client
        existante : son `iat` est alors celui de la session, pas celui de l'émission.
        Sans ce réessai, un import de plusieurs centaines de comptes s'interrompt au
        premier 401. Rejouer est sans risque : un 401 signifie que la requête a été
        rejetée, donc sans effet de bord.
        """
        url = f"{self._admin_base}{path}"
        response = self._send(method, url, headers=self._headers(), **kwargs)
        if response.status_code == 401:
            logger.info("Jeton admin refusé (401), renouvellement et réessai : %s", path)
            self.reset_token()
            response = self._send(method, url, headers=self._headers(), **kwargs)
        return response

    def _get(self, path: str) -> requests.Response:
        return self._request(requests.get, path)

    def _post(self, path: str, json: Any | None = None) -> requests.Response:
        return self._request(requests.post, path, json=json)

    def _put(self, path: str, json: Any | None = None) -> requests.Response:
        return self._request(requests.put, path, json=json)

    def _delete(self, path: str) -> requests.Response:
        return self._request(requests.delete, path)

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

    #: Clé du cache pour la racine, qui n'a pas d'identifiant de parent.
    _RACINE = ""

    def invalidate_group_cache(self, parent_id: str | None = None) -> None:
        """Oublie les listages mémorisés, pour un parent ou pour tous."""
        if parent_id is None:
            self._groups_cache.clear()
        else:
            self._groups_cache.pop(parent_id, None)

    def _remember_group(self, parent_id: str, group_id: str, name: str) -> None:
        """Ajoute un groupe tout juste créé au listage mémorisé de son parent."""
        cached = self._groups_cache.get(parent_id)
        if cached is not None and not any(g.get("id") == group_id for g in cached):
            cached.append({"id": group_id, "name": name})

    def list_top_groups(self) -> list[dict]:
        cached = self._groups_cache.get(self._RACINE)
        if cached is not None:
            return cached
        r = self._get("/groups?briefRepresentation=false")
        if r.status_code != 200:
            raise KeycloakAdminError(f"list_groups:{r.status_code}")
        groups = r.json() or []
        self._groups_cache[self._RACINE] = groups
        return groups

    def get_group(self, group_id: str) -> dict:
        r = self._get(f"/groups/{group_id}")
        if r.status_code != 200:
            raise KeycloakAdminError(f"get_group:{r.status_code}")
        return r.json() or {}

    def find_group_by_path(self, path: str) -> dict | None:
        target = (path or "").strip()
        if not target.startswith("/"):
            target = f"/{target}"
        if target == "/":
            return None

        parts = [p for p in target.strip("/").split("/") if p]
        if not parts:
            return None

        roots = self.list_top_groups()
        current = next((g for g in roots if (g.get("name") or "") == parts[0]), None)
        if not current:
            return None
        if len(parts) == 1:
            return current

        current_id = current.get("id")
        if not current_id:
            return None
        for seg in parts[1:]:
            children = self.get_subgroups(current_id)
            nxt = next((g for g in children if (g.get("name") or "") == seg), None)
            if not nxt:
                return None
            current = nxt
            current_id = current.get("id")
            if not current_id:
                break
        return current

    def get_subgroups(self, parent_id: str) -> list[dict]:
        # Endpoint dédié aux sous-groupes (plus fiable que le champ subGroups de /groups/{id}).
        # On itère par pages pour éviter les réponses tronquées.
        cached = self._groups_cache.get(parent_id)
        if cached is not None:
            return cached
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
                fallback = data.get("subGroups") or []
                self._groups_cache[parent_id] = fallback
                return fallback

            batch = r.json() or []
            if not isinstance(batch, list):
                break
            out.extend(batch)
            if len(batch) < page_size:
                break
            first += page_size
        self._groups_cache[parent_id] = out
        return out

    def create_child_group(self, parent_id: str, name: str) -> str:
        r = self._post(f"/groups/{parent_id}/children", json={"name": name})
        if r.status_code == 409:
            # Le groupe existe déjà (course condition / duplication) :
            # on relit avec retries pour gérer la latence d'indexation Keycloak.
            # Le listage mémorisé ne peut pas contenir ce groupe : on le jette.
            for _ in range(5):
                self.invalidate_group_cache(parent_id)
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
                self._remember_group(parent_id, j["id"], name)
                return j["id"]
        except ValueError:
            pass
        loc = r.headers.get("Location", "")
        gid = loc.rstrip("/").split("/")[-1] if loc else ""
        if not gid:
            raise KeycloakAdminError("create_child_group_no_id")
        self._remember_group(parent_id, gid, name)
        return gid

    def create_top_group(self, name: str) -> str:
        r = self._post("/groups", json={"name": name})
        if r.status_code == 409:
            # Déjà présent : on retourne l'id existant.
            self.invalidate_group_cache(self._RACINE)
            for g in self.list_top_groups():
                if g.get("name") == name and g.get("id"):
                    return g["id"]
            raise KeycloakAdminError("create_top_group_conflict_unresolved")
        if r.status_code not in (200, 201):
            raise KeycloakAdminError(f"create_top_group_failed:{r.status_code}:{r.text[:200]}")
        loc = r.headers.get("Location", "")
        gid = loc.rstrip("/").split("/")[-1]
        self._remember_group(self._RACINE, gid, name)
        return gid

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

    def ensure_reserve_referent_group(self, code: str) -> str:
        root = settings.KEYCLOAK_GROUP_RESERVES
        return self.ensure_path_under_root(root, [code, "referent"])

    def ensure_application_group(self, slug: str) -> str:
        root = settings.KEYCLOAK_GROUP_APPLICATIONS
        return self.ensure_path_under_root(root, [slug])

    def ensure_super_admin_group(self) -> str:
        return self.ensure_root(settings.KEYCLOAK_GROUP_SUPER_ADMIN)

    def ensure_application_admin_group(self, slug: str) -> str:
        root = settings.KEYCLOAK_GROUP_APPLICATIONS
        return self.ensure_path_under_root(root, [slug, "admin"])

    def user_join_group(self, user_id: str, group_id: str) -> None:
        h = {"Authorization": f"Bearer {self.get_access_token()}"}
        r = self._send(requests.put, f"{self._admin_base}/users/{user_id}/groups/{group_id}", headers=h)
        if r.status_code not in (200, 204):
            raise KeycloakAdminError(f"user_join_group:{r.status_code}:{r.text[:200]}")
        # Vérification best-effort: si l'API renvoie la liste des groupes, on confirme l'effet.
        check = self._send(requests.get, f"{self._admin_base}/users/{user_id}/groups", headers=h)
        if check.status_code == 200:
            groups = check.json() or []
            in_group = any(g.get("id") == group_id for g in groups if isinstance(g, dict))
            if not in_group:
                raise KeycloakAdminError("user_join_group_not_effective")
        elif check.status_code not in (401, 403):
            logger.warning("user groups check failed: %s %s", check.status_code, check.text[:200])

    def user_leave_group(self, user_id: str, group_id: str) -> None:
        h = {"Authorization": f"Bearer {self.get_access_token()}"}
        r = self._send(requests.delete, f"{self._admin_base}/users/{user_id}/groups/{group_id}", headers=h)
        if r.status_code not in (200, 204):
            raise KeycloakAdminError(f"user_leave_group:{r.status_code}:{r.text[:200]}")

    def _create_user_error_detail(self, response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return "Impossible de créer le compte Keycloak."
        if not isinstance(payload, dict):
            return "Impossible de créer le compte Keycloak."
        field = payload.get("field")
        error_message = payload.get("errorMessage")
        if field == "username" and error_message == "error-invalid-length":
            return "L'identifiant doit contenir entre 3 et 255 caractères (contrainte Keycloak)."
        if field == "username":
            return "Identifiant refusé par Keycloak."
        if field == "email":
            return "Adresse e-mail refusée par Keycloak (déjà utilisée ou invalide)."
        return "Impossible de créer le compte Keycloak."

    def create_user(
        self,
        username: str,
        email: str,
        first_name: str,
        last_name: str,
        password: str | None = None,
        temporary_password: bool = False,
        require_verify_email: bool = False,
        function_value: str | None = None,
        email_verified: bool = False,
        extra_attributes: dict[str, list[str]] | None = None,
        imported_password_credential: dict | None = None,
    ) -> str:
        body = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": True,
            "emailVerified": email_verified,
        }
        if imported_password_credential:
            body["credentials"] = [imported_password_credential]
        elif password:
            body["credentials"] = [{"type": "password", "value": password, "temporary": temporary_password}]
        else:
            raise KeycloakAdminError("password_or_import_required")
        if require_verify_email:
            body["requiredActions"] = ["VERIFY_EMAIL"]
        attrs: dict[str, list[str]] = dict(extra_attributes or {})
        if function_value is not None:
            attrs["function"] = [str(function_value).strip()]
        if attrs:
            body["attributes"] = attrs
        r = self._post("/users", json=body)
        if r.status_code not in (200, 201):
            detail = self._create_user_error_detail(r)
            logger.error("create_user %s: %s", r.status_code, r.text[:500])
            raise KeycloakAdminError("create_user_failed", detail)
        loc = r.headers.get("Location", "")
        uid = loc.rstrip("/").split("/")[-1] if loc else ""
        if not uid:
            uid = self.find_user_by_username(username) or ""
        if not uid:
            raise KeycloakAdminError("create_user_no_id")
        return uid

    def delete_user(self, user_id: str) -> None:
        """Supprime un compte Keycloak.

        Sert à compenser une création lorsque l'écriture miroir vers la base
        historique échoue : Keycloak n'étant pas transactionnel, c'est le seul moyen
        de revenir à l'état initial. Un 404 est tenu pour un succès (déjà absent).
        """
        r = self._delete(f"/users/{user_id}")
        if r.status_code not in (200, 204, 404):
            logger.error("delete_user %s: %s", r.status_code, r.text[:300])
            raise KeycloakAdminError("delete_user_failed")

    def find_user_by_username(self, username: str) -> str | None:
        r = self._get(f"/users?username={requests.utils.quote(username)}&exact=true")
        if r.status_code != 200:
            return None
        arr = r.json() or []
        if not arr:
            return None
        return arr[0].get("id")

    def search_users(self, query: str, max_count: int = 20) -> list[dict]:
        q = (query or "").strip()
        if not q:
            return []
        r = self._get(f"/users?search={requests.utils.quote(q)}&max={max_count}")
        if r.status_code != 200:
            raise KeycloakAdminError(f"search_users_failed:{r.status_code}")
        payload = r.json() or []
        if not isinstance(payload, list):
            return []
        return payload

    def send_verify_email(self, user_id: str, client_id: str | None = None) -> None:
        params: dict[str, str] = {}
        if client_id:
            params["client_id"] = client_id
        h = {"Authorization": f"Bearer {self.get_access_token()}"}
        r = self._send(
            requests.put,
            f"{self._admin_base}/users/{user_id}/send-verify-email",
            headers=h,
            params=params or None,
        )
        if r.status_code not in (200, 204):
            logger.error("send_verify_email %s: %s", r.status_code, r.text[:500])
            raise KeycloakAdminError(f"send_verify_email_failed:{r.status_code}")

    def update_user_profile(
        self,
        user_id: str,
        *,
        username: str | None = None,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        function_value: str | None = None,
    ) -> None:
        current_resp = self._get(f"/users/{user_id}")
        if current_resp.status_code != 200:
            raise KeycloakAdminError(f"get_user_failed:{current_resp.status_code}")
        data = current_resp.json() or {}

        if username is not None:
            data["username"] = username
        if email is not None:
            data["email"] = email
        if first_name is not None:
            data["firstName"] = first_name
        if last_name is not None:
            data["lastName"] = last_name

        attrs = data.get("attributes") or {}
        if function_value is not None:
            attrs["function"] = [function_value]
        data["attributes"] = attrs

        resp = self._put(f"/users/{user_id}", json=data)
        if resp.status_code not in (200, 204):
            logger.error("update_user_profile %s: %s", resp.status_code, resp.text[:500])
            raise KeycloakAdminError(f"update_user_failed:{resp.status_code}")

    def set_user_attribute(self, user_id: str, name: str, value: str) -> None:
        """Pose un attribut sur un compte sans toucher au reste de sa représentation."""
        current = self._get(f"/users/{user_id}")
        if current.status_code != 200:
            raise KeycloakAdminError(f"get_user_failed:{current.status_code}")
        data = current.json() or {}
        attrs = data.get("attributes") or {}
        attrs[name] = [str(value)]
        data["attributes"] = attrs
        resp = self._put(f"/users/{user_id}", json=data)
        if resp.status_code not in (200, 204):
            logger.error("set_user_attribute %s: %s", resp.status_code, resp.text[:300])
            raise KeycloakAdminError(f"update_user_failed:{resp.status_code}")

    def get_user(self, user_id: str) -> dict:
        r = self._get(f"/users/{user_id}")
        if r.status_code != 200:
            raise KeycloakAdminError(f"get_user_failed:{r.status_code}")
        return r.json() or {}

    def get_user_groups(self, user_id: str) -> list[dict]:
        r = self._get(f"/users/{user_id}/groups?briefRepresentation=false")
        if r.status_code != 200:
            raise KeycloakAdminError(f"get_user_groups_failed:{r.status_code}")
        payload = r.json() or []
        return payload if isinstance(payload, list) else []

    def list_group_members(self, group_id: str, max_count: int = 200) -> list[dict]:
        r = self._get(f"/groups/{group_id}/members?first=0&max={max_count}")
        if r.status_code != 200:
            raise KeycloakAdminError(f"list_group_members:{r.status_code}")
        payload = r.json() or []
        if not isinstance(payload, list):
            return []
        return payload

    def count_group_members(self, group_id: str, page_size: int = 200) -> int:
        total = 0
        first = 0
        while True:
            r = self._get(f"/groups/{group_id}/members?first={first}&max={page_size}")
            if r.status_code != 200:
                raise KeycloakAdminError(f"count_group_members:{r.status_code}")
            batch = r.json() or []
            if not isinstance(batch, list):
                break
            total += len(batch)
            if len(batch) < page_size:
                break
            first += page_size
        return total

    def list_all_group_members(self, group_id: str, page_size: int = 200) -> list[dict]:
        out: list[dict] = []
        first = 0
        while True:
            r = self._get(f"/groups/{group_id}/members?first={first}&max={page_size}")
            if r.status_code != 200:
                raise KeycloakAdminError(f"list_all_group_members:{r.status_code}")
            batch = r.json() or []
            if not isinstance(batch, list):
                break
            out.extend(batch)
            if len(batch) < page_size:
                break
            first += page_size
        return out

    def list_all_users(self, page_size: int = 200) -> list[dict]:
        out: list[dict] = []
        first = 0
        while True:
            r = self._get(f"/users?first={first}&max={page_size}")
            if r.status_code != 200:
                raise KeycloakAdminError(f"list_all_users:{r.status_code}")
            batch = r.json() or []
            if not isinstance(batch, list):
                break
            out.extend(batch)
            if len(batch) < page_size:
                break
            first += page_size
        return out
