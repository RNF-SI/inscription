export type NavMenuItem = {
    nom: string;
    classFa: 'fas' | 'fab';
    nomFa: string;
    lien: string;
};

export const AppConfig = {
    "ID_APPLICATION_GEONATURE": 6,
    "API_ENDPOINT": "http://127.0.0.1:5070",
    "appName": "Plateformes RNF",
    "appTitle": "Plateformes de réserves naturelles de France",
    "appSubTitle": "Tous les outils pour vous accompagner dans vos projets",
    "creditHeaderImage": "RNN Baie de St-Brieuc - © P. PIERRE",
    "menu": [
        {
            "nom":"accueil", 
            "classFa":"fas",
            "nomFa":"house",
            "lien":""
        },
        {
            "nom":"Mon compte",
            "classFa":"fas",
            "nomFa":"bars-progress",
            "lien":"mon-compte"
        }
        // ,{
        //     "nom":"explorer", 
        //     "classFa":"fas" as const,
        //     "nomFa":"magnifying-glass" as const,
        //     "lien":"explorer"
        // }
    ] as NavMenuItem[],
    "menucompte": [
        {
            "texte":"Déconnexion",
            "classFa":"fas",
            "nomFa":"right-from-bracket",
            "lien":"logout"
        }
    ]
}