import { Component, OnInit } from '@angular/core';
import { faKey, faUserPlus, faArrowUpRightFromSquare } from '@fortawesome/free-solid-svg-icons';
import { faFacebook, faInstagram, faGithub, faLinkedin} from '@fortawesome/free-brands-svg-icons';

@Component({
  selector: 'app-home',
  templateUrl: './home.component.html',
  styleUrls: ['./home.component.scss']
})
export class HomeComponent implements OnInit {

  constructor() { }

  faKey = faKey;
  faUserPlus = faUserPlus;
  faArrowUpRightFromSquare = faArrowUpRightFromSquare;

  Applications = [
    {
      'nom': 'GeoNature Saisie', 
      'url':'https://geonature-saisie.reserves-naturelles.org',
      'image': 'geonature-saisie.png',
      'description': 'L\'application GeoNature Saisie est mise à disposition des organismes gestionnaires ne disposant pas des moyens de déployer leur propre infrastructure. Plus d\'informations <a href="https://assoconnect.reserves-naturelles.org/page/2095754-geonature-dans-les-reserves">en cliquant sur ce lien</a>.',
      'si': true
    },
    {
      'nom': 'GeoNature Global',
      'url':'https://geonature.reserves-naturelles.org',
      'image': 'geonature-global.png',
      'description': 'L\'application GeoNature Global vise à centraliser les données des réserves utilisant GeoNature. Elle permet également la saisie ou l\'import de données de certains protocoles pour tous, comme le PSDRF.',
      'si': true
    },
    {
      'nom': 'BAO Ancrage',
      'url': 'https://ancrage.reserves-naturelles.org/',
      'image': 'ancrage.png',
      'description': 'La Boîte à Outils Ancrage Territorial vous donne toutes les ressources pour mettre en place et mener à bien votre diagnostique d\'ancrage territorial.',
      'si': true
    },
    {
      'nom': 'SOCLE',
      'url': 'https://socle.reserves-naturelles.org/',
      'image': 'socle.png',
      'description': 'SOCLE permet la saisie des données du patrimoine géologique d\'une réserve, selon les cahiers de géologie édités par RNF.',
      'si': false
    },
    {
      'nom': 'Natur\'Adapt',
      'url': 'https://naturadapt.com/',
      'image': 'naturadapt.png',
      'description': 'Natur\'Adapt héberge et anime une communauté autour du thème de l\'adaptation des aires protégées au changement climatique.',
      'si': false
    },
    {
      'nom': 'ODASE',
      'url': null,
      'image': 'odase.png',
      'description': 'L\'ODASE sera un outil de saisie, de centralisation et d\'exploration des données socio-économique des réserves naturelles. <b>Lancement prévu : 2024</b>',
      'si': true
    },
    {
      'nom': 'Plateforme OPNL',
      'url': null,
      'image': 'opnl.png',
      'description': 'La plateforme OPNL permettra de centraliser toutes les informations relatives aux activités et productions des membres et partenaires de l\'observatoire du patrimoine naturel littoral. <b>Lancement prévu : Automne 2023</b>',
      'si': true
    },
    {
      'nom': 'AssoConnect',
      'url': 'https://assoconnect.reserves-naturelles.org/',
      'image': 'assoconnect.png',
      'description': 'AssoConnect est le portail des membres de RNF. Il permet d\'accéder à l\'ensemble des informations sur les activités de l\'association et ses commissions. Il permet également de renouveler son adhésion et d\'accéder à la boutique.',
      'si': false
    },
    {
      'nom': 'Site Internet',
      'url': 'https://www.reserves-naturelles.org/',
      'image': 'site.png',
      'description': 'Le site internet de Réserves Naturelles de France et le portail grand public qui permet d\'accéder à toutes les informations utiles sur les réserves et le réseau.',
      'si': false
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
    }
    // {
    //   'nom':,
    //   'url':,
    //   'image':,
    //   'description':,
    //   'si': false
    // }
  ]

  ngOnInit(): void {
  }

}