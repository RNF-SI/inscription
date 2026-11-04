import { Injectable, inject } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { RouterStateSnapshot, TitleStrategy } from '@angular/router';

import { AppConfig } from 'src/conf/app.config';

/**
 * Titre de l'onglet : « <page> · Plateformes RNF ».
 *
 * Posé ici parce que la mesure d'audience en a besoin : sans `title` sur les
 * routes, Matomo rangerait toutes les visites sous le titre de `index.html`.
 * Les onglets et les favoris y gagnent au passage.
 *
 * `buildTitle` n'est pas touché — il continue de rendre le seul `title` de la
 * route, que `MatomoService` envoie tel quel : les rapports listent « Mon
 * compte », sans le nom de l'application répété sur chaque ligne.
 */
@Injectable({ providedIn: 'root' })
export class PageTitleStrategy extends TitleStrategy {
  private readonly title = inject(Title);

  override updateTitle(snapshot: RouterStateSnapshot): void {
    const page = this.buildTitle(snapshot);
    this.title.setTitle(page ? `${page} · ${AppConfig.appName}` : AppConfig.appName);
  }
}
