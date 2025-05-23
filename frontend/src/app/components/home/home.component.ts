import { Component, OnInit } from '@angular/core';
import { faArrowUpRightFromSquare, faKey, faUserPlus } from '@fortawesome/free-solid-svg-icons';
import { User } from '../../home-rnf/models/user.model';
import { AuthService } from '../../home-rnf/services/auth-service.service';
import { Organisme } from '../../models/models';

@Component({
  selector: 'app-home',
  templateUrl: './home.component.html',
  styleUrls: ['./home.component.scss']
})
export class HomeComponent implements OnInit {

  constructor(

    private _authService: AuthService
  ) { }
  protected organismes: Organisme[];
  faKey = faKey;
  faUserPlus = faUserPlus;
  faArrowUpRightFromSquare = faArrowUpRightFromSquare;

  Applications = [
    {
      'nom': 'GeoNature Saisie',
      'url': 'https://geonature-saisie.reserves-naturelles.org',
      'image': 'geonature-saisie.png',
      'description': 'L\'application GeoNature Saisie est mise à disposition des organismes gestionnaires ne disposant pas des moyens de déployer leur propre infrastructure. Plus d\'informations <a href="https://assoconnect.reserves-naturelles.org/page/2095754-geonature-dans-les-reserves">en cliquant sur ce lien</a>.',
      'si': true
    },
    {
      'nom': 'GeoNature PSDRF',
      'url': 'https://geonature.reserves-naturelles.org',
      'image': 'geonature-global.png',
      'description': 'Le module PSDRF de GeoNature permet l\'import et la vérification de données du protocole, ainsi que l\'édition d\'un rapport dendrométrique.',
      'si': true
    },
    {
      'nom': 'BAO Diagnostic d\'Ancrage Territorial',
      'url': 'https://ancrage.reserves-naturelles.org/',
      'image': 'ancrage.png',
      'description': 'La Boîte à Outils de Diagnostic d\'Ancrage Territorial vous donne toutes les ressources pour mettre en place et mener à bien votre diagnostic d\'ancrage territorial.',
      'si': true
    },
    {
      'nom': 'SOCLE',
      'url': 'https://socle.reserves-naturelles.org/',
      'image': 'socle.png',
      'description': 'SOCLE permet la saisie des données du patrimoine géologique d\'une réserve naturelle, selon les cahiers de géologie édités par RNF.',
      'si': true
    },
    {
      'nom': 'Natur\'Adapt',
      'url': 'https://naturadapt.com/',
      'image': 'naturadapt.png',
      'description': 'Natur\'Adapt héberge et anime une communauté autour du thème de l\'adaptation des aires protégées au changement climatique.',
      'si': false
    },
    // {
    //   'nom': 'ODASE',
    //   'url': null,
    //   'image': 'odase.png',
    //   'description': 'L\'ODASE sera un outil de saisie, de centralisation et d\'exploration des données socio-économique des réserves naturelles. <b>Lancement prévu : 2024</b>',
    //   'si': true
    // },
    {
      'nom': 'Plateforme OPNL',
      'url': 'https://opnl.fr',
      'image': 'opnl.png',
      'description': 'La plateforme OPNL permet de centraliser toutes les informations relatives aux activités et productions des membres et partenaires de l\'observatoire du patrimoine naturel littoral.',
      'si': true
    },
    {
      'nom': 'Portail des membres',
      'url': 'https://www.portail.reserves-naturelles.org/',
      'image': 'assoconnect.png',
      'description': 'Le portail des membres de RNF permet d\'accéder à l\'ensemble des informations sur les activités de l\'association et ses commissions. Il permet également de renouveler son adhésion et d\'accéder à la boutique.',
      'si': false
    },
    {
      'nom': 'Site Internet',
      'url': 'https://www.reserves-naturelles.org/',
      'image': 'site.png',
      'description': 'Le site internet de Réserves Naturelles de France est le portail grand public qui permet d\'accéder à toutes les informations utiles sur les réserves naturelles et le réseau.',
      'si': true
    },
    {
      'nom': 'Pearltrees',
      'url': 'https://www.pearltrees.com/ressources_rnf',
      'image': 'pearltrees.png',
      'description': 'Le pearltrees de RNF est une plateforme de mise à disposition et de diffusion de ressources en aide à la gestion des aires protégées.',
      'si': false
    },
    {
      'nom': 'Boutique uniformes',
      'url': 'https://rnf-boutique.fr/',
      'image': 'boutique.png',
      'description': 'La boutique uniforme est la plateforme de commandes des uniformes et autres équipements pour les agents des réserves.',
      'si': false
    },
    {
      'nom': 'Tourbières du réseau',
      'url': 'https://tourbieres.reserves-naturelles.org/',
      'image': 'tourbieres.png',
      'description': 'RNF a centralisé les données des tourbières du réseau. Retrouvez les réserves et leur contact selon les caractéristiques de leurs tourbières.',
      'si': true
    }
  ]

  ngOnInit(): void {
  }

  public get user(): null | User {
    return this._authService.getCurrentUser();
  }

}
