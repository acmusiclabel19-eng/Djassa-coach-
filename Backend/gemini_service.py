import os
import json
from google import genai
from google.genai import types
from typing import Optional, List

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

def get_client():
    if GOOGLE_API_KEY:
        return genai.Client(api_key=GOOGLE_API_KEY)
    return None

def detect_transaction_intent(message: str, produits: list, language: str = "fr") -> dict:
    """Detect if the message contains a transaction intent (sale, expense, debt)"""
    client = get_client()
    if not client:
        return {"has_transaction": False, "error": "API not configured"}
    
    produits_list = ", ".join([f"{p['nom']} ({p['prix_unitaire']} FCFA)" for p in produits[:30]])
    
    is_english = language == "en"
    
    if is_english:
        prompt = f"""You are an expert assistant at extracting transaction intents.
Analyze this message and determine if it contains an intent to record a transaction (sale, expense, debt).

Message: "{message}"

Products available in the shop:
{produits_list}

Respond ONLY with valid JSON in this exact format:
{{
    "has_transaction": true/false,
    "transaction_type": "vente" | "depense" | "dette" | null,
    "details": {{
        "produit_nom": "exact product name or null",
        "quantite": number or null,
        "prix_unitaire": price in FCFA or null,
        "montant_total": total amount or null,
        "client_nom": "client name for debt or null",
        "description": "expense description or null",
        "categorie": "expense category or null"
    }},
    "confidence": 0.0-1.0,
    "missing_info": ["list of missing info"]
}}

Examples:
- "Sold 2 bags of rice at 15000" -> sale, product: rice, quantity: 2, price: 15000
- "I sold 3 soaps" -> sale, product: soap, quantity: 3
- "Expense electricity 20000 FCFA" -> expense, description: electricity, amount: 20000
- "Mamadou owes me 5000 francs" -> debt, client: Mamadou, amount: 5000
- "What's my profit?" -> has_transaction: false

JSON:"""
    else:
        prompt = f"""Tu es un assistant expert en extraction d'intentions de transaction.
Analyse ce message et détermine s'il contient une intention d'enregistrer une transaction (vente, dépense, dette).

Message: "{message}"

Produits disponibles dans la boutique:
{produits_list}

Réponds UNIQUEMENT en JSON valide avec ce format:
{{
    "has_transaction": true/false,
    "transaction_type": "vente" | "depense" | "dette" | null,
    "details": {{
        "produit_nom": "nom du produit ou null",
        "quantite": nombre ou null,
        "prix_unitaire": prix en FCFA ou null,
        "montant_total": montant total ou null,
        "client_nom": "nom du client pour dette ou null",
        "description": "description de la dépense ou null",
        "categorie": "categorie de dépense ou null"
    }},
    "confidence": 0.0-1.0,
    "missing_info": ["liste des infos manquantes"]
}}

Exemples:
- "Vendu 2 sacs de riz à 15000" -> vente, produit: riz, quantite: 2, prix: 15000
- "J'ai vendu 3 savons" -> vente, produit: savon, quantite: 3
- "Dépense électricité 20000 FCFA" -> dépense, description: électricité, montant: 20000
- "Mamadou me doit 5000 francs" -> dette, client: Mamadou, montant: 5000
- "Quel est mon bénéfice?" -> has_transaction: false

JSON:"""

    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        
        text = (response.text or "").strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        
        import re
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return result
        return {"has_transaction": False}
    except Exception as e:
        return {"has_transaction": False, "error": str(e)}

def parse_voice_input(transcript: str, produits: list) -> dict:
    client = get_client()
    if not client:
        return {
            "success": False,
            "error": "API Gemini non configurée"
        }
    
    produits_list = ", ".join([f"{p['nom']} ({p['prix_unitaire']} FCFA)" for p in produits[:20]])
    
    prompt = f"""Tu es un assistant pour une application de gestion de boutique ivoirienne.
Analyse cette transcription vocale et extrait les informations de vente.

Transcription: "{transcript}"

Produits disponibles dans la boutique:
{produits_list}

Réponds UNIQUEMENT en JSON valide avec ce format exact:
{{
    "success": true ou false,
    "produit_nom": "nom exact du produit trouvé ou null",
    "quantite": nombre entier ou null,
    "prix_unitaire": prix en FCFA ou null,
    "confiance": nombre entre 0 et 1
}}

Si tu ne comprends pas ou si les informations sont incomplètes, mets success à false.
Exemples de transcriptions valides:
- "3 savons à 500 francs" -> produit: savon, quantite: 3, prix: 500
- "vente 2 kilos de riz" -> produit: riz, quantite: 2
- "j'ai vendu 5 bouteilles" -> quantite: 5

Réponds uniquement avec le JSON, pas d'explication."""

    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        
        text = (response.text or "").strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        
        result = json.loads(text.strip())
        return result
    except json.JSONDecodeError:
        return {
            "success": False,
            "error": "Réponse IA invalide"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

def format_fcfa(montant: int) -> str:
    formatted = f"{montant:,}".replace(",", " ")
    return f"{formatted} FCFA"

CECILE_SYSTEM_PROMPT = """Tu es Cécile, une assistante IA chaleureuse et experte pour l'application Djassa Coach, 
une application de gestion financière pour les commerçants ivoiriens.

Tu parles français avec un style amical et accessible, adapté aux commerçants de Côte d'Ivoire.
Tu peux utiliser occasionnellement des expressions locales ivoiriennes pour créer une connexion.

🎯 TES CAPACITÉS PRINCIPALES:
1. CONSULTER les données financières (ventes, dettes, dépenses, stock)
2. ANALYSER les tendances et donner des conseils
3. AIDER à enregistrer des transactions par la voix
4. MOTIVER et encourager l'entrepreneur

📊 DONNÉES FINANCIÈRES DE LA BOUTIQUE "{nom_boutique}":
{financial_data}

📝 RÈGLES IMPORTANTES:
- Sois concise mais chaleureuse (réponses de 2-4 phrases max)
- Utilise les vraies données ci-dessus pour répondre aux questions
- Si on te demande "mes ventes", réponds avec les chiffres réels
- Si on te demande "mes dettes", liste les clients endettés
- Pour enregistrer une vente/dépense, guide l'utilisateur vers la bonne page
- Utilise le format monétaire: "125 000 FCFA"
- Ne donne jamais de conseils médicaux ou juridiques
- Encourage toujours l'utilisateur

🗣️ EXEMPLES DE RÉPONSES:
- "Tes ventes aujourd'hui: 45 000 FCFA. C'est bien parti ! 💪"
- "Tu as 3 dettes en cours pour un total de 25 000 FCFA."
- "Conseil: Essaie de relancer Amadou qui doit 10 000 FCFA depuis 15 jours."

Historique de conversation:
{history}"""

def chat_with_cecile(message: str, context: dict, history: Optional[List[dict]] = None, financial_data: str = "") -> dict:
    client = get_client()
    if not client:
        return {
            "success": False,
            "error": "API Gemini non configurée. Veuillez configurer la clé GOOGLE_API_KEY.",
            "response": None
        }
    
    if history is None:
        history = []
    
    history_str = ""
    for msg in history[-10:]:
        role = "Utilisateur" if msg.get("role") == "user" else "Cécile"
        history_str += f"{role}: {msg.get('content', '')}\n"
    
    system_prompt = CECILE_SYSTEM_PROMPT.format(
        nom_boutique=context.get('nom_boutique', 'Ma Boutique'),
        financial_data=financial_data,
        history=history_str
    )
    
    full_prompt = f"{system_prompt}\n\nUtilisateur: {message}\n\nCécile:"
    
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=full_prompt
        )
        
        return {
            "success": True,
            "response": (response.text or "").strip(),
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "response": None
        }
