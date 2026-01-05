from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime
import re

class SignupRequest(BaseModel):
    nom_boutique: str = Field(..., min_length=3, max_length=100)
    telephone: str = Field(..., min_length=8, max_length=20)
    pin: str = Field(..., min_length=4, max_length=4)
    pin_confirm: str = Field(..., min_length=4, max_length=4)
    
    @validator('telephone')
    def validate_telephone(cls, v):
        if not re.match(r'^0[0-9]{8,9}$', v):
            raise ValueError('Format téléphone invalide (ex: 0701234567)')
        return v
    
    @validator('pin')
    def validate_pin(cls, v):
        if not v.isdigit():
            raise ValueError('Le PIN doit contenir uniquement des chiffres')
        return v
    
    @validator('pin_confirm')
    def validate_pin_confirm(cls, v, values):
        if 'pin' in values and v != values['pin']:
            raise ValueError('Les PINs ne correspondent pas')
        return v

class LoginRequest(BaseModel):
    telephone: str
    pin: str

class VerifyPinRequest(BaseModel):
    pin: str

class TokenResponse(BaseModel):
    boutique_id: str
    token: str
    features: dict
    nom_boutique: str

class DashboardResponse(BaseModel):
    ventes_aujourdhui: int
    depenses_aujourdhui: int
    dettes_totales: int
    dettes_critiques: int
    stock_alertes: int
    ventes_7_jours: List[dict]
    objectif_actif: Optional[dict] = None

class ProduitCreate(BaseModel):
    nom: str = Field(..., min_length=2, max_length=100)
    prix_unitaire: int = Field(..., ge=100)
    quantite_stock: int = Field(default=0, ge=0)
    seuil_alerte: int = Field(default=5, ge=0)
    categorie: Optional[str] = None

class ProduitResponse(BaseModel):
    id: str
    nom: str
    prix_unitaire: int
    quantite_stock: int
    seuil_alerte: int
    categorie: Optional[str]
    
    class Config:
        from_attributes = True

class VenteCreate(BaseModel):
    produit_id: str
    quantite: int = Field(..., ge=1)

class VenteResponse(BaseModel):
    id: str
    produit: dict
    quantite: int
    montant_total: int
    date_vente: datetime
    
    class Config:
        from_attributes = True

class DepenseCreate(BaseModel):
    categorie: str = Field(...)
    montant: int = Field(..., ge=100)
    description: Optional[str] = Field(default=None, max_length=500)

class DepenseResponse(BaseModel):
    id: str
    categorie: str
    montant: int
    description: Optional[str]
    date_depense: datetime
    
    class Config:
        from_attributes = True

class DetteCreate(BaseModel):
    nom_client: str = Field(..., min_length=2, max_length=100)
    telephone_client: Optional[str] = None
    montant_initial: int = Field(..., ge=500)

class DetteResponse(BaseModel):
    id: str
    nom_client: str
    telephone_client: Optional[str]
    montant_initial: int
    montant_restant: int
    date_creation: datetime
    statut: str
    jours_depuis_creation: int = 0
    
    class Config:
        from_attributes = True

class PaiementDetteCreate(BaseModel):
    montant_paye: int = Field(..., ge=1)

class ObjectifCreate(BaseModel):
    type: str
    montant_cible: int = Field(..., ge=10000)
    date_debut: datetime
    date_fin: datetime
    
    @validator('type')
    def validate_type(cls, v):
        types = ['journalier', 'hebdomadaire', 'mensuel']
        if v not in types:
            raise ValueError(f'Type doit être: {", ".join(types)}')
        return v

class VoiceParseRequest(BaseModel):
    transcript: str = Field(..., max_length=500)

class VoiceParseResponse(BaseModel):
    success: bool
    produit: Optional[dict] = None
    quantite: Optional[int] = None
    prix_unitaire: Optional[int] = None
    confiance: float = 0.0
    quota_restant: int = 0

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)

class ChatResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    quota_restant: int = 0
    quota_max: int = 20

class ChatHistoryMessage(BaseModel):
    role: str
    content: str
    created_at: datetime

class ConversationMessage(BaseModel):
    text: str
    sender: str
    timestamp: str

class ChatbotRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    conversation_history: List[ConversationMessage] = Field(default_factory=list)
    language: str = Field(default="fr")
    auto_record_transactions: bool = Field(default=True)

class TransactionRecorded(BaseModel):
    type: str
    details: dict
    success: bool
    message: str

class ChatbotResponse(BaseModel):
    response: str
    suggestions: List[str] = Field(default_factory=list)
    transaction_recorded: Optional[TransactionRecorded] = None
    proactive_advice: Optional[str] = None

class FrequentDepenseResponse(BaseModel):
    id: str
    categorie: str
    montant: int
    usage_count: int
    
    class Config:
        from_attributes = True

class DepenseCategoryCreate(BaseModel):
    nom: str = Field(..., min_length=2, max_length=50)
    icone: str = Field(..., min_length=1, max_length=10)

class DepenseCategoryResponse(BaseModel):
    id: str
    nom: str
    icone: str
    usage_count: int
    
    class Config:
        from_attributes = True
