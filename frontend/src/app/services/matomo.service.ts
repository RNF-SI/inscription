import { DestroyRef, Injectable, inject } from '@angular/core';
import { NavigationEnd, Router, TitleStrategy } from '@angular/router';
import { filter } from 'rxjs';

import { environment } from 'src/environments/environment';

/**
 * File d'attente de Matomo : les commandes y sont empilées avant même que le
 * script ne soit chargé, puis rejouées dans l'ordre à son arrivée. C'est
 * l'interface officielle du traqueur — on ne manipule jamais l'objet
 * `Piwik`/`Matomo` directement.
 */
type MatomoCommand = unknown[];

declare global {
  interface Window {
    _paq?: MatomoCommand[];
  }
}

/**
 * Mesure d'audience de la plateforme, confiée à l'instance Matomo de Réserves
 * naturelles de France — comme la vitrine Cicada, qui porte le même service.
 *
 * Configurée **sans cookie** (`disableCookies`) et respectant l'en-tête « Do
 * Not Track ». C'est ce qui permet à l'application de rester sans bandeau de
 * consentement : la CNIL exempte la mesure d'audience dès lors qu'elle ne
 * dépose rien sur le poste du visiteur et ne sert qu'à produire des
 * statistiques anonymes. La contrepartie est connue et assumée : un même
 * usager revenant un autre jour est compté comme nouveau.
 *
 * L'anonymisation des adresses IP n'a, elle, pas d'équivalent côté navigateur :
 * elle se règle sur l'instance (Administration → Confidentialité → Anonymiser
 * les données) et doit y rester active.
 *
 * Rien n'est transmis sur le compte lui-même : pas de `setUserId`, pas de
 * dimension personnalisée. Les statistiques disent quelles pages sont
 * consultées, pas par qui — c'est volontaire, l'application manipule des
 * données de compte.
 *
 * **Ni la chaîne de requête ni le fragment ne partent vers Matomo**, seulement
 * le chemin : `/auth/callback` porte le code d'autorisation OIDC et
 * `/nouveau-mot-de-passe` le jeton de réinitialisation. Un secret à usage
 * unique n'a rien à faire dans un journal de statistiques, et Matomo conserve
 * l'URL telle qu'on la lui donne. Les paramètres de campagne (`utm_*`) sont
 * écartés du même coup : la plateforme ne reçoit pas de trafic de campagne.
 *
 * Désactivée tant que `matomoUrl` ou `matomoSiteId` manque — c'est le cas des
 * builds de développement, qui n'ont rien à faire dans les statistiques de
 * production.
 */
@Injectable({ providedIn: 'root' })
export class MatomoService {
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly titleStrategy = inject(TitleStrategy);

  /** Chemin de la dernière page comptée ; `null` tant qu'aucune ne l'a été. */
  private lastTrackedPath: string | null = null;

  /** Garde-fou : deux abonnements compteraient chaque page deux fois. */
  private started = false;

  /**
   * Démarre le suivi. À n'appeler qu'une fois, au démarrage de l'application.
   */
  start(): void {
    const { matomoUrl, matomoSiteId } = environment;
    if (!matomoUrl || !matomoSiteId || this.started) {
      return;
    }
    this.started = true;

    const paq = (window._paq ??= []);

    // Réglages de confidentialité AVANT le premier comptage : une commande
    // empilée après `trackPageView` n'aurait plus d'effet sur lui.
    paq.push(['disableCookies']);
    paq.push(['setDoNotTrack', true]);
    paq.push(['setTrackerUrl', `${matomoUrl}/matomo.php`]);
    paq.push(['setSiteId', matomoSiteId]);

    this.loadScript(matomoUrl);

    // La navigation initiale du routeur peut s'être achevée avant ce point —
    // auquel cas aucun `NavigationEnd` ne passera plus — ou juste après. Les
    // deux cas sont couverts : ce qui est déjà arrivé est compté tout de
    // suite, le reste par l'abonnement.
    if (this.router.lastSuccessfulNavigation()) {
      this.trackCurrentPage(paq);
    }

    // L'application est monopage : seul le premier affichage est une vraie
    // requête HTTP. Les suivants — « Mon compte », l'administration, le retour
    // à l'accueil — doivent être signalés à la main.
    const subscription = this.router.events
      .pipe(filter((event) => event instanceof NavigationEnd))
      .subscribe(() => this.trackCurrentPage(paq));

    this.destroyRef.onDestroy(() => subscription.unsubscribe());
  }

  /**
   * Compte l'affichage de la page courante, sauf si elle vient de l'être.
   *
   * Seul le chemin est comparé : une navigation qui ne change que la chaîne de
   * requête ou le fragment n'est pas une nouvelle page vue.
   */
  private trackCurrentPage(paq: MatomoCommand[]): void {
    const path = this.currentPath();
    if (path === this.lastTrackedPath) {
      return;
    }

    // Matomo attribue sinon le trafic à la page du premier chargement : sans
    // cela, toute l'application semblerait avoir été consultée depuis
    // l'accueil.
    if (this.lastTrackedPath !== null) {
      paq.push(['setReferrerUrl', `${window.location.origin}${this.lastTrackedPath}`]);
    }
    this.lastTrackedPath = path;

    // L'URL est donnée explicitement : sans `setCustomUrl`, Matomo retiendrait
    // l'adresse du premier chargement pour toute la session. Recomposée à
    // partir du seul chemin, jamais `location.href` — cf. l'en-tête de classe.
    paq.push(['setCustomUrl', `${window.location.origin}${path}`]);
    // Le titre est demandé au routeur plutôt que lu dans `document.title` :
    // c'est Angular qui le pose sur le document, et il le fait après nous —
    // Matomo recevrait sinon le titre de la page précédente.
    paq.push(['setDocumentTitle', this.currentTitle()]);
    paq.push(['trackPageView']);
    // Comptabilise les clics sortants (les liens vers les applications du SI,
    // depuis l'accueil) et les téléchargements. À réarmer après chaque page :
    // les liens de la nouvelle n'existaient pas avant.
    paq.push(['enableLinkTracking']);
  }

  /**
   * Chemin de la page courante, chaîne de requête et fragment écartés.
   *
   * Lu sur le routeur plutôt que dans `window.location` : une route qui
   * redirige (`/nouveau-mot-de-passe` sans jeton exploitable) ferait sinon
   * compter la page d'arrivée à la place de celle qui a été demandée.
   */
  private currentPath(): string {
    const tree = this.router.parseUrl(this.router.url);
    tree.queryParams = {};
    tree.fragment = null;
    return this.router.serializeUrl(tree);
  }

  /** Titre de la page courante, tel que déclaré sur la route. */
  private currentTitle(): string {
    return this.titleStrategy.buildTitle(this.router.routerState.snapshot) ?? document.title;
  }

  /** Injecte `matomo.js`, sans bloquer l'affichage. */
  private loadScript(matomoUrl: string): void {
    const script = document.createElement('script');
    script.src = `${matomoUrl}/matomo.js`;
    script.async = true;
    script.defer = true;
    document.head.appendChild(script);
  }
}
