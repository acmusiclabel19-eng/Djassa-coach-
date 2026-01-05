# Djassa Coach - PWA Financière pour Commerçants Ivoiriens

## Vue d'ensemble
Djassa Coach est une application web progressive (PWA) de gestion financière conçue pour les commerçants ivoiriens. Elle permet de gérer les ventes, dépenses, dettes clients, et le stock de produits avec une interface mobile-first et la saisie vocale IA.

## Architecture

### Stack Technique
- **Frontend**: React + TypeScript + Tailwind CSS + Recharts
- **Backend**: FastAPI (Python) + SQLite + SQLAlchemy
- **IA**: Google Gemini API pour la saisie vocale
- **PWA**: Service Workers + IndexedDB (Dexie.js)

### Structure du Projet
```
├── backend/
│   └── app/
│       ├── main.py          # Point d'entrée FastAPI
│       ├── models.py        # Modèles SQLAlchemy
│       ├── schemas.py       # Schémas Pydantic
│       ├── auth.py          # Authentification JWT + bcrypt
│       ├── database.py      # Configuration SQLite
│       └── gemini_service.py # Intégration Gemini
├── frontend/
│   ├── src/
│   │   ├── pages/           # Pages React (Dashboard, Ventes, etc.)
│   │   ├── components/      # Composants réutilisables
│   │   ├── hooks/           # Hooks personnalisés (useFinanceStats, usePrivacyMode)
│   │   └── lib/             # API client avec cache + utilitaires
│   └── public/              # Assets statiques + PWA
└── run.py                   # Script de démarrage combiné
```

## Fonctionnalités

### MVP
- Inscription/Connexion avec PIN 4 chiffres (style Facebook)
- Dashboard avec statistiques en temps réel ("Ventes du Jour")
- Gestion des ventes avec calcul automatique (style Facebook avec grille produits)
- Suivi des dépenses par catégorie
- Gestion des dettes clients avec paiements partiels
- Gestion des produits et du stock
- Saisie vocale IA (Gemini gemini-1.5-flash)
- Mode discret (montants floutés sur tous les KPIs incluant stock)
- Chatbot Cécile amélioré (assistant IA style Instagram DM, Gemini 1.5 Flash):
  - Connexion base de données temps réel (ventes, dépenses, dettes, stock)
  - Enregistrement automatique des transactions par langage naturel (confiance >= 0.8)
  - Rate limiting: 10 auto-transactions par 5 minutes
  - Audit logging complet (action "create_auto", source "cecile")
  - Messages de feedback utilisateur pour échecs de validation
  - Intelligence émotionnelle et conseils proactifs (alertes dépenses > ventes)
  - Reconnaissance vocale bilingue (fr-FR / en-US)
- Page Rapports (filtres type/période, résumés, téléchargement)
- FloatingActionMenu (style WhatsApp) avec calculatrice et rapport
- 10 messages motivationnels rotatifs dans le header
- Support multilingue (FR/EN actif, ES/AR/ZH à venir)
- Mode sombre complet

### Performance (Nouveau)
- **Splash Screen** animé (< 2s) avec logo et slogan
- **Lazy Loading** de toutes les pages React
- **Cache API** avec TTL 30s scopé par boutique
- **Preloading parallèle** des données critiques (Dashboard, Produits)
- Hook **useFinanceStats** pour calculs automatiques bénéfices/pertes

### Dashboard Amélioré
- Nom de boutique dynamique dans header
- Slogan centré : "Transformez chaque vente en succès"
- Mode discret sur tous les KPIs (ventes, dettes, stock, dépenses)
- Courbes circulaires SVG pour bénéfices (vert) et dépenses (rouge)
- Bouton Rapport stylé avec gradient vert
- Carte résultat net avec indicateur positif/négatif

### Menu Profil (Nouveau)
- Profil synchronisé avec données réelles (nom boutique, téléphone depuis localStorage)
- Initiales dynamiques générées à partir du nom de boutique
- Centre d'aide avec FAQ intégrée (modal bilingue FR/EN)
- Politique de confidentialité (modal bilingue)
- Conditions d'utilisation (modal bilingue)
- Bouton Partager l'application

### Sécurité
- Hash bcrypt pour les PINs
- UUID pour les IDs (anti-énumération)
- Rate limiting sur les endpoints sensibles
- Soft delete pour toutes les données
- Audit trail complet
- Cache scopé par boutique (pas de fuite de données)
- Déconnexion sécurisée avec clearCache()

## Configuration

### Variables d'environnement requises
- `GOOGLE_API_KEY`: Clé API Google Gemini pour la saisie vocale
- `SESSION_SECRET`: Clé secrète pour les tokens JWT

### Ports
- Frontend (Vite): 5000 (proxy vers backend)
- Backend (FastAPI): 8000

## Format Monétaire
Format strict: "125 000 FCFA" (espace milliers + FCFA)

## Couleurs
- Bleu Royal `#2563EB` (primaire)
- Gris Perle `#F3F4F6` (fond)
- Vert `#10B981` (ventes/bénéfices)
- Rouge `#DC2626` (dettes/pertes)
- Orange `#F59E0B` (dépenses)

## Design
- Premium Fintech avec rounded-2xl, shadow-lg
- Mobile-first avec max-w-md constraint
- Inter font
- Touch targets 52px minimum
- Animations slide-up pour menus flottants
