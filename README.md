# ELF Construction — socle web multiutilisateur

**Statut : version de développement déployable, PAS logiciel financier validé pour la production.**

## Fonctions présentes
- Interface française responsive (Mac, Windows, iPhone via navigateur)
- Authentification, rôles admin / gestionnaire / direction (lecture seule)
- Accueil et indicateurs séparant clients, fournisseurs, Larbi/ELF et dettes personnelles Larbi
- Registre : devis, avenants, encaissements, commandes, règlements, dépenses, avances et remboursements Larbi
- Chantiers (création, budget, archivage), clients et fournisseurs
- Correction, annulation logique, historique d'audit, justificatifs PDF/images
- Import XLSX avec aperçu, choix des colonnes, contrôle des lignes, dédoublonnage par fichier/feuille/ligne, traçabilité et annulation de lot
- Export CSV

## Limites à corriger AVANT d'importer les vrais chiffres
- **Pas de garantie zéro bug.** Tests d'intégration et tests réels multiutilisateurs non effectués ici (dépendances Flask indisponibles dans l'environnement de génération).
- L'import Excel suppose une feuille de tableau avec en-tête et des dates `AAAA-MM-JJ`, une seule catégorie par import ; pas encore de mappage fournisseur/client, des dates françaises ni de réconciliation intelligente entre commandes et dépenses. Les montants de plusieurs fichiers qui décrivent la même opération ne sont pas automatiquement rapprochés.
- Les totaux clients sont basés sur les **devis**, pas sur des factures exigibles. Les commandes ne représentent pas nécessairement des dettes échues. Le résultat chantier et la trésorerie certifiée ne sont pas encore calculés.
- Les comptes sont créés par l'admin avec mot de passe temporaire à communiquer séparément ; invitations par e-mail et récupération autonome des mots de passe non implémentées.
- Pas de sauvegarde automatique/restauration testée, de migrations de schéma, ni de suite de tests métier complète. Il faut les ajouter avant une exploitation financière.
- Les justificatifs sont stockés en base de données : surveiller quotas et capacité.
- L'hébergement Render gratuit peut être mis en veille. **Ne pas utiliser SQLite sur le disque éphémère de Render** : les données pourraient disparaître lors d'un redéploiement/redémarrage.

## Installation locale de développement
1. Installer Python 3.11+ et Git.
2. Dans ce dossier : `python -m venv .venv` puis activer l'environnement et `pip install -r requirements.txt`.
3. Définir `ADMIN_EMAIL`, `ADMIN_PASSWORD` (12+ caractères) et `SECRET_KEY` (longue chaîne aléatoire) dans l'environnement. Ne jamais les enregistrer dans Git.
4. `python app.py` puis ouvrir `http://127.0.0.1:5000`.
5. À la première connexion, changer le mot de passe administrateur.

## Déploiement gratuit envisagé
1. Créer un dépôt GitHub **privé appartenant au propriétaire d'ELF**, y pousser ces fichiers. Ne pas y mettre de mots de passe ni de données financières.
2. Créer une base PostgreSQL persistante chez un fournisseur disposant d'une offre gratuite compatible (vérifier les conditions, quotas, durée et sauvegardes en vigueur). Copier la chaîne de connexion `DATABASE_URL` uniquement dans les variables secrètes Render.
3. Sur Render, créer un **Web Service** depuis le dépôt GitHub (ou utiliser `render.yaml` si disponible pour le plan gratuit). `Build Command`: `pip install -r requirements.txt`. `Start Command`: `gunicorn app:app`.
4. Définir les secrets `DATABASE_URL`, `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `COOKIE_SECURE=1`. Ne pas utiliser de SQLite en ligne.
5. Attendre le statut opérationnel, vérifier `/health`, ouvrir l'URL HTTPS Render, se connecter, créer Mustapha comme gestionnaire et tester sur deux appareils.
6. Tester imports, annulations, accès lecture seule, export, restauration et sauvegardes **avec des données fictives** avant tout usage réel.

### Important sur le coût
Le code est libre d'utilisation et le dépôt privé GitHub peut être gratuit. Un déploiement **sans paiement** est envisageable si les offres gratuites sont disponibles, mais aucune garantie de disponibilité permanente, de quotas suffisants ou de sauvegardes garanties n'est possible. Ne pas activer un plan payant sans accord.

## Sauvegarde
L'export CSV de l'application sauvegarde les opérations mais **pas** les pièces jointes, utilisateurs, chantiers ni l'audit. Il ne remplace **pas** une sauvegarde PostgreSQL complète et restaurable. La mise en production requiert un plan de sauvegarde/restauration externe réellement testé.

## Structure
- `app.py` : serveur Flask, schéma et règles métier
- `templates/` : écrans HTML
- `static/style.css` : interface responsive
- `render.yaml` : configuration indicative Render
- `requirements.txt` : dépendances

## Prochaine étape technique
Faire une revue de code et tester le projet dans un environnement disposant de Flask, puis compléter le rapprochement des imports, les sauvegardes et la gestion des invitations avant déploiement réel.
