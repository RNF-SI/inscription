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
            "classFa":"fas" as const,
            "nomFa":"house" as const,
            "lien":""
        }
        // ,{
        //     "nom":"explorer", 
        //     "classFa":"fas" as const,
        //     "nomFa":"magnifying-glass" as const,
        //     "lien":"explorer"
        // }
    ],
    "menucompte": [
        {
            "texte":"Déconnexion",
            "classFa":"fas" as const,
            "nomFa":"right-from-bracket" as const,
            "lien":"logout"
        }

    ]
}