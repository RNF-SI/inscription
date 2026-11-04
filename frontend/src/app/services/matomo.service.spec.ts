import { TestBed } from '@angular/core/testing';
import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';

import { MatomoService } from './matomo.service';
import { environment } from 'src/environments/environment';

@Component({ standalone: false, template: '' })
class PageBidonComponent {}

describe('MatomoService', () => {
  const urlOrigine = environment.matomoUrl;
  const siteOrigine = environment.matomoSiteId;

  /** Les commandes empilées, sous forme comparable. */
  function commandes(): string[][] {
    return (window._paq ?? []).map((commande) => commande.map(String));
  }

  function scriptsMatomo(): HTMLScriptElement[] {
    return Array.from(document.head.querySelectorAll<HTMLScriptElement>('script[src*="matomo"]'));
  }

  beforeEach(() => {
    delete window._paq;
    TestBed.configureTestingModule({
      imports: [
        RouterTestingModule.withRoutes([
          { path: '', component: PageBidonComponent, title: 'Accueil' },
          { path: 'inscription', component: PageBidonComponent, title: 'Inscription' },
        ]),
      ],
      declarations: [PageBidonComponent],
    });
  });

  afterEach(() => {
    environment.matomoUrl = urlOrigine;
    environment.matomoSiteId = siteOrigine;
    delete window._paq;
    scriptsMatomo().forEach((script) => script.remove());
  });

  it('ne charge rien tant que la configuration est incomplète', async () => {
    environment.matomoUrl = null;
    environment.matomoSiteId = '7';

    TestBed.inject(MatomoService).start();
    await TestBed.inject(Router).navigateByUrl('/');

    expect(window._paq).toBeUndefined();
    expect(scriptsMatomo().length).toBe(0);
  });

  it('ne compte rien si le numéro de site manque — mieux vaut aucune statistique', () => {
    environment.matomoUrl = 'https://matomo.invalid';
    environment.matomoSiteId = '';

    TestBed.inject(MatomoService).start();

    expect(window._paq).toBeUndefined();
  });

  describe('une fois configuré', () => {
    let router: Router;

    beforeEach(() => {
      environment.matomoUrl = 'https://matomo.invalid';
      environment.matomoSiteId = '7';
      router = TestBed.inject(Router);
    });

    it('règle la confidentialité avant le premier comptage', async () => {
      TestBed.inject(MatomoService).start();
      await router.navigateByUrl('/');

      const empilees = commandes().map(([nom]) => nom);
      expect(empilees.slice(0, 4)).toEqual([
        'disableCookies',
        'setDoNotTrack',
        'setTrackerUrl',
        'setSiteId',
      ]);
      expect(empilees.indexOf('trackPageView')).toBeGreaterThan(empilees.indexOf('disableCookies'));
    });

    it('compte la page sous le titre de sa route', async () => {
      TestBed.inject(MatomoService).start();
      await router.navigateByUrl('/inscription');

      expect(commandes()).toContain(['setDocumentTitle', 'Inscription']);
      expect(commandes()).toContain(['trackPageView']);
    });

    it("n'envoie pas la chaîne de requête, qui porte des secrets", async () => {
      TestBed.inject(MatomoService).start();
      await router.navigateByUrl('/inscription?token=SECRET#bas');

      const urls = commandes().filter(([nom]) => nom === 'setCustomUrl');
      expect(urls).toEqual([['setCustomUrl', `${window.location.origin}/inscription`]]);
    });

    it('déclare la page précédente en référent', async () => {
      TestBed.inject(MatomoService).start();
      await router.navigateByUrl('/');
      await router.navigateByUrl('/inscription');

      expect(commandes()).toContain(['setReferrerUrl', `${window.location.origin}/`]);
      expect(commandes().filter(([nom]) => nom === 'trackPageView').length).toBe(2);
    });

    it('ne compte pas deux fois une page dont seule la requête change', async () => {
      TestBed.inject(MatomoService).start();
      await router.navigateByUrl('/inscription?onglet=1');
      await router.navigateByUrl('/inscription?onglet=2');

      expect(commandes().filter(([nom]) => nom === 'trackPageView').length).toBe(1);
    });

    it('ne démarre qu’une fois', async () => {
      const matomo = TestBed.inject(MatomoService);
      matomo.start();
      matomo.start();
      await router.navigateByUrl('/inscription');

      expect(commandes().filter(([nom]) => nom === 'trackPageView').length).toBe(1);
    });
  });
});
