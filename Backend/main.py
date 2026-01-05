from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta, date
import json
import os

from .database import engine, get_db, Base
from .models import Boutique, Produit, Vente, Depense, Dette, PaiementDette, Objectif, VoiceLog, AuditLog, ChatMessage, ChatLog, FrequentDepense, DepenseCategory
from .schemas import (
    SignupRequest, LoginRequest, VerifyPinRequest, TokenResponse, DashboardResponse,
    ProduitCreate, ProduitResponse, VenteCreate, VenteResponse,
    DepenseCreate, DepenseResponse, DetteCreate, DetteResponse,
    PaiementDetteCreate, ObjectifCreate, VoiceParseRequest, VoiceParseResponse,
    ChatRequest, ChatResponse, DepenseCategoryCreate
)
from .auth import (
    hash_pin, verify_pin, create_access_token, get_current_boutique, create_session
)
from .gemini_service import parse_voice_input, chat_with_cecile, detect_transaction_intent

Base.metadata.create_all(bind=engine)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Djassa Coach API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def format_fcfa(montant: int) -> str:
    formatted = f"{montant:,}".replace(",", " ")
    return f"{formatted} FCFA"

def log_audit(db: Session, boutique_id: str, action: str, table_name: str, record_id: str, ip_address: str, old_values: dict = None, new_values: dict = None):
    audit = AuditLog(
        boutique_id=boutique_id,
        action=action,
        table_name=table_name,
        record_id=record_id,
        ip_address=ip_address,
        old_values=json.dumps(old_values) if old_values else None,
        new_values=json.dumps(new_values) if new_values else None
    )
    db.add(audit)
    db.commit()

@app.post("/api/auth/signup", response_model=TokenResponse)
@limiter.limit("5/minute")
async def signup(request: Request, data: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(Boutique).filter(
        Boutique.telephone == data.telephone,
        Boutique.deleted_at == None
    ).first()
    
    if existing:
        raise HTTPException(status_code=409, detail="Ce numéro de téléphone est déjà enregistré")
    
    pin_hash, pin_salt = hash_pin(data.pin)
    
    boutique = Boutique(
        nom=data.nom_boutique,
        telephone=data.telephone,
        pin_hash=pin_hash,
        pin_salt=pin_salt,
        last_login_ip=request.client.host
    )
    db.add(boutique)
    db.commit()
    db.refresh(boutique)
    
    token = create_access_token(boutique.id)
    create_session(db, boutique.id, token, request.client.host, request.headers.get("user-agent"))
    
    log_audit(db, boutique.id, "signup", "boutiques", boutique.id, request.client.host)
    
    features = json.loads(boutique.features_json)
    
    return TokenResponse(
        boutique_id=boutique.id,
        token=token,
        features=features,
        nom_boutique=boutique.nom
    )

@app.post("/api/auth/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    boutique = db.query(Boutique).filter(
        Boutique.telephone == data.telephone,
        Boutique.deleted_at == None,
        Boutique.active == True
    ).first()
    
    if not boutique:
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    
    if boutique.locked_until and boutique.locked_until > datetime.utcnow():
        raise HTTPException(status_code=423, detail="Compte temporairement bloqué")
    
    if not verify_pin(data.pin, boutique.pin_hash):
        boutique.failed_login_attempts += 1
        if boutique.failed_login_attempts >= 3:
            boutique.locked_until = datetime.utcnow() + timedelta(minutes=15)
        db.commit()
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    
    boutique.failed_login_attempts = 0
    boutique.locked_until = None
    boutique.last_login_at = datetime.utcnow()
    boutique.last_login_ip = request.client.host
    db.commit()
    
    token = create_access_token(boutique.id)
    create_session(db, boutique.id, token, request.client.host, request.headers.get("user-agent"))
    
    log_audit(db, boutique.id, "login", "boutiques", boutique.id, request.client.host)
    
    features = json.loads(boutique.features_json)
    
    return TokenResponse(
        boutique_id=boutique.id,
        token=token,
        features=features,
        nom_boutique=boutique.nom
    )

@app.post("/api/auth/verify-pin")
async def verify_pin_endpoint(
    request: Request,
    data: VerifyPinRequest,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    if not verify_pin(data.pin, boutique.pin_hash):
        log_audit(db, boutique.id, "failed_pin_verify", "boutiques", boutique.id, request.client.host)
        raise HTTPException(status_code=401, detail="Code PIN incorrect")
    
    log_audit(db, boutique.id, "pin_verified", "boutiques", boutique.id, request.client.host)
    return {"success": True}

@app.get("/api/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    ventes_aujourdhui = db.query(func.coalesce(func.sum(Vente.montant_total), 0)).filter(
        Vente.boutique_id == boutique.id,
        Vente.date_vente >= today_start,
        Vente.date_vente <= today_end,
        Vente.deleted_at == None
    ).scalar()
    
    depenses_aujourdhui = db.query(func.coalesce(func.sum(Depense.montant), 0)).filter(
        Depense.boutique_id == boutique.id,
        Depense.date_depense >= today_start,
        Depense.date_depense <= today_end,
        Depense.deleted_at == None
    ).scalar()
    
    dettes_totales = db.query(func.coalesce(func.sum(Dette.montant_restant), 0)).filter(
        Dette.boutique_id == boutique.id,
        Dette.statut == 'en_cours',
        Dette.deleted_at == None
    ).scalar()
    
    limite_critique = datetime.utcnow() - timedelta(days=15)
    dettes_critiques = db.query(func.count(Dette.id)).filter(
        Dette.boutique_id == boutique.id,
        Dette.statut == 'en_cours',
        Dette.date_creation <= limite_critique,
        Dette.deleted_at == None
    ).scalar()
    
    stock_alertes = db.query(func.count(Produit.id)).filter(
        Produit.boutique_id == boutique.id,
        Produit.quantite_stock <= Produit.seuil_alerte,
        Produit.active == True,
        Produit.deleted_at == None
    ).scalar()
    
    ventes_7_jours = []
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        date_start = datetime.combine(date, datetime.min.time())
        date_end = datetime.combine(date, datetime.max.time())
        
        montant = db.query(func.coalesce(func.sum(Vente.montant_total), 0)).filter(
            Vente.boutique_id == boutique.id,
            Vente.date_vente >= date_start,
            Vente.date_vente <= date_end,
            Vente.deleted_at == None
        ).scalar()
        
        ventes_7_jours.append({
            "date": date.strftime("%Y-%m-%d"),
            "jour": ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"][date.weekday()],
            "montant": montant
        })
    
    objectif_actif = None
    objectif = db.query(Objectif).filter(
        Objectif.boutique_id == boutique.id,
        Objectif.active == True,
        Objectif.date_debut <= datetime.utcnow(),
        Objectif.date_fin >= datetime.utcnow(),
        Objectif.deleted_at == None
    ).first()
    
    if objectif:
        realise = db.query(func.coalesce(func.sum(Vente.montant_total), 0)).filter(
            Vente.boutique_id == boutique.id,
            Vente.date_vente >= objectif.date_debut,
            Vente.date_vente <= objectif.date_fin,
            Vente.deleted_at == None
        ).scalar()
        
        progression = min(100, (realise / objectif.montant_cible) * 100) if objectif.montant_cible > 0 else 0
        
        objectif_actif = {
            "type": objectif.type,
            "cible": objectif.montant_cible,
            "realise": realise,
            "progression": round(progression, 1)
        }
    
    return DashboardResponse(
        ventes_aujourdhui=ventes_aujourdhui,
        depenses_aujourdhui=depenses_aujourdhui,
        dettes_totales=dettes_totales,
        dettes_critiques=dettes_critiques,
        stock_alertes=stock_alertes,
        ventes_7_jours=ventes_7_jours,
        objectif_actif=objectif_actif
    )

@app.get("/api/produits")
async def get_produits(
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    produits = db.query(Produit).filter(
        Produit.boutique_id == boutique.id,
        Produit.active == True,
        Produit.deleted_at == None
    ).all()
    
    return [{
        "id": p.id,
        "nom": p.nom,
        "prix_unitaire": p.prix_unitaire,
        "quantite_stock": p.quantite_stock,
        "seuil_alerte": p.seuil_alerte,
        "categorie": p.categorie
    } for p in produits]

@app.post("/api/produits")
async def create_produit(
    request: Request,
    data: ProduitCreate,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    existing = db.query(Produit).filter(
        Produit.boutique_id == boutique.id,
        Produit.nom == data.nom,
        Produit.deleted_at == None
    ).first()
    
    if existing:
        raise HTTPException(status_code=409, detail="Un produit avec ce nom existe déjà")
    
    produit = Produit(
        boutique_id=boutique.id,
        nom=data.nom,
        prix_unitaire=data.prix_unitaire,
        quantite_stock=data.quantite_stock,
        seuil_alerte=data.seuil_alerte,
        categorie=data.categorie
    )
    db.add(produit)
    db.commit()
    db.refresh(produit)
    
    log_audit(db, boutique.id, "create_product", "produits", produit.id, request.client.host)
    
    return {"id": produit.id, "nom": produit.nom, "prix_unitaire": produit.prix_unitaire}

@app.patch("/api/produits/{produit_id}/stock")
async def update_stock(
    request: Request,
    produit_id: str,
    ajustement: int,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    produit = db.query(Produit).filter(
        Produit.id == produit_id,
        Produit.boutique_id == boutique.id,
        Produit.deleted_at == None
    ).first()
    
    if not produit:
        raise HTTPException(status_code=404, detail="Produit non trouvé")
    
    nouvelle_quantite = produit.quantite_stock + ajustement
    if nouvelle_quantite < 0:
        raise HTTPException(status_code=400, detail="Stock insuffisant")
    
    produit.quantite_stock = nouvelle_quantite
    db.commit()
    
    return {"nouvelle_quantite": nouvelle_quantite}

@app.delete("/api/produits/{produit_id}")
async def delete_produit(
    produit_id: str,
    request: Request,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    produit = db.query(Produit).filter(
        Produit.id == produit_id,
        Produit.boutique_id == boutique.id,
        Produit.deleted_at == None
    ).first()
    
    if not produit:
        raise HTTPException(status_code=404, detail="Produit non trouvé")
    
    produit.deleted_at = datetime.utcnow()
    produit.active = False
    db.commit()
    
    log_audit(db, boutique.id, "delete_product", "produits", produit.id, request.client.host,
              old_values={"nom": produit.nom, "stock": produit.quantite_stock})
    
    return {"success": True}

@app.get("/api/ventes")
async def get_ventes(
    limit: int = 20,
    offset: int = 0,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    ventes = db.query(Vente).filter(
        Vente.boutique_id == boutique.id,
        Vente.deleted_at == None
    ).order_by(Vente.date_vente.desc()).offset(offset).limit(limit).all()
    
    total = db.query(func.count(Vente.id)).filter(
        Vente.boutique_id == boutique.id,
        Vente.deleted_at == None
    ).scalar()
    
    return {
        "ventes": [{
            "id": v.id,
            "produit": {"id": v.produit.id, "nom": v.produit.nom},
            "quantite": v.quantite,
            "montant_total": v.montant_total,
            "date_vente": v.date_vente.isoformat()
        } for v in ventes],
        "total": total,
        "has_next": offset + limit < total
    }

@app.post("/api/ventes")
async def create_vente(
    request: Request,
    data: VenteCreate,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    produit = db.query(Produit).filter(
        Produit.id == data.produit_id,
        Produit.boutique_id == boutique.id,
        Produit.deleted_at == None
    ).first()
    
    if not produit:
        raise HTTPException(status_code=404, detail="Produit non trouvé")
    
    if produit.quantite_stock < data.quantite:
        raise HTTPException(status_code=400, detail="Stock insuffisant")
    
    montant_total = produit.prix_unitaire * data.quantite
    
    vente = Vente(
        boutique_id=boutique.id,
        produit_id=produit.id,
        quantite=data.quantite,
        prix_unitaire=produit.prix_unitaire,
        montant_total=montant_total,
        ip_address=request.client.host
    )
    
    produit.quantite_stock -= data.quantite
    
    db.add(vente)
    db.commit()
    db.refresh(vente)
    
    log_audit(db, boutique.id, "create_sale", "ventes", vente.id, request.client.host,
              new_values={"montant": montant_total, "produit": produit.nom})
    
    return {
        "vente_id": vente.id,
        "montant_total": montant_total,
        "stock_restant": produit.quantite_stock
    }

@app.delete("/api/ventes/{vente_id}")
async def delete_vente(
    vente_id: str,
    request: Request,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    vente = db.query(Vente).filter(
        Vente.id == vente_id,
        Vente.boutique_id == boutique.id,
        Vente.deleted_at == None
    ).first()
    
    if not vente:
        raise HTTPException(status_code=404, detail="Vente non trouvée")
    
    produit = db.query(Produit).filter(Produit.id == vente.produit_id).first()
    if produit:
        produit.quantite_stock += vente.quantite
    
    vente.deleted_at = datetime.utcnow()
    db.commit()
    
    log_audit(db, boutique.id, "delete_sale", "ventes", vente.id, request.client.host,
              old_values={"montant": vente.montant_total, "quantite": vente.quantite})
    
    return {"success": True, "stock_restaure": produit.quantite_stock if produit else 0}

@app.get("/api/depenses")
async def get_depenses(
    limit: int = 20,
    offset: int = 0,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    depenses = db.query(Depense).filter(
        Depense.boutique_id == boutique.id,
        Depense.deleted_at == None
    ).order_by(Depense.date_depense.desc()).offset(offset).limit(limit).all()
    
    total = db.query(func.count(Depense.id)).filter(
        Depense.boutique_id == boutique.id,
        Depense.deleted_at == None
    ).scalar()
    
    return {
        "depenses": [{
            "id": d.id,
            "categorie": d.categorie,
            "montant": d.montant,
            "description": d.description,
            "date_depense": d.date_depense.isoformat()
        } for d in depenses],
        "total": total,
        "has_next": offset + limit < total
    }

@app.post("/api/depenses")
async def create_depense(
    request: Request,
    data: DepenseCreate,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    depense = Depense(
        boutique_id=boutique.id,
        categorie=data.categorie,
        montant=data.montant,
        description=data.description,
        ip_address=request.client.host
    )
    db.add(depense)
    
    montant_bucket = (data.montant // 500) * 500
    if montant_bucket < 500:
        montant_bucket = 500
    
    existing_freq = db.query(FrequentDepense).filter(
        FrequentDepense.boutique_id == boutique.id,
        FrequentDepense.categorie == data.categorie,
        FrequentDepense.montant_bucket == montant_bucket
    ).first()
    
    if existing_freq:
        existing_freq.usage_count += 1
        existing_freq.last_used_at = datetime.utcnow()
    else:
        new_freq = FrequentDepense(
            boutique_id=boutique.id,
            categorie=data.categorie,
            montant_bucket=montant_bucket
        )
        db.add(new_freq)
    
    db.commit()
    db.refresh(depense)
    
    log_audit(db, boutique.id, "create_expense", "depenses", depense.id, request.client.host)
    
    return {"id": depense.id, "montant": depense.montant}

@app.delete("/api/depenses/{depense_id}")
async def delete_depense(
    depense_id: str,
    request: Request,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    depense = db.query(Depense).filter(
        Depense.id == depense_id,
        Depense.boutique_id == boutique.id,
        Depense.deleted_at == None
    ).first()
    
    if not depense:
        raise HTTPException(status_code=404, detail="Dépense non trouvée")
    
    depense.deleted_at = datetime.utcnow()
    db.commit()
    
    log_audit(db, boutique.id, "delete_expense", "depenses", depense.id, request.client.host,
              old_values={"montant": depense.montant, "categorie": depense.categorie})
    
    return {"success": True}

@app.get("/api/depenses/frequentes")
async def get_frequent_depenses(
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    frequentes = db.query(FrequentDepense).filter(
        FrequentDepense.boutique_id == boutique.id
    ).order_by(FrequentDepense.usage_count.desc()).limit(8).all()
    
    return [{
        "id": f.id,
        "categorie": f.categorie,
        "montant": f.montant_bucket,
        "usage_count": f.usage_count
    } for f in frequentes]

@app.get("/api/depenses/categories")
async def get_depense_categories(
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    categories = db.query(DepenseCategory).filter(
        DepenseCategory.boutique_id == boutique.id,
        DepenseCategory.active == True,
        DepenseCategory.deleted_at == None
    ).order_by(DepenseCategory.usage_count.desc()).all()
    
    return [{
        "id": c.id,
        "nom": c.nom,
        "icone": c.icone,
        "usage_count": c.usage_count
    } for c in categories]

@app.post("/api/depenses/categories")
async def create_depense_category(
    request: Request,
    data: DepenseCategoryCreate,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    existing = db.query(DepenseCategory).filter(
        DepenseCategory.boutique_id == boutique.id,
        DepenseCategory.nom == data.nom,
        DepenseCategory.deleted_at == None
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Cette catégorie existe déjà")
    
    category = DepenseCategory(
        boutique_id=boutique.id,
        nom=data.nom,
        icone=data.icone
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    
    log_audit(db, boutique.id, "create_expense_category", "depense_categories", category.id, request.client.host)
    
    return {"id": category.id, "nom": category.nom, "icone": category.icone}

@app.get("/api/dettes")
async def get_dettes(
    statut: str = "en_cours",
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    dettes = db.query(Dette).filter(
        Dette.boutique_id == boutique.id,
        Dette.statut == statut,
        Dette.deleted_at == None
    ).order_by(Dette.date_creation.asc()).all()
    
    now = datetime.utcnow()
    
    return [{
        "id": d.id,
        "nom_client": d.nom_client,
        "telephone_client": d.telephone_client,
        "montant_initial": d.montant_initial,
        "montant_restant": d.montant_restant,
        "date_creation": d.date_creation.isoformat(),
        "statut": d.statut,
        "jours_depuis_creation": (now - d.date_creation).days
    } for d in dettes]

@app.post("/api/dettes")
async def create_dette(
    request: Request,
    data: DetteCreate,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    dette = Dette(
        boutique_id=boutique.id,
        nom_client=data.nom_client,
        telephone_client=data.telephone_client,
        montant_initial=data.montant_initial,
        montant_restant=data.montant_initial
    )
    db.add(dette)
    db.commit()
    db.refresh(dette)
    
    log_audit(db, boutique.id, "create_debt", "dettes", dette.id, request.client.host)
    
    return {"id": dette.id, "montant": dette.montant_initial}

@app.delete("/api/dettes/{dette_id}")
async def delete_dette(
    dette_id: str,
    request: Request,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    dette = db.query(Dette).filter(
        Dette.id == dette_id,
        Dette.boutique_id == boutique.id,
        Dette.deleted_at == None
    ).first()
    
    if not dette:
        raise HTTPException(status_code=404, detail="Dette non trouvée")
    
    dette.deleted_at = datetime.utcnow()
    db.commit()
    
    log_audit(db, boutique.id, "delete_debt", "dettes", dette.id, request.client.host,
              old_values={"montant": dette.montant_initial, "client": dette.nom_client})
    
    return {"success": True}

@app.post("/api/dettes/{dette_id}/paiement")
async def payer_dette(
    request: Request,
    dette_id: str,
    data: PaiementDetteCreate,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    dette = db.query(Dette).filter(
        Dette.id == dette_id,
        Dette.boutique_id == boutique.id,
        Dette.deleted_at == None
    ).first()
    
    if not dette:
        raise HTTPException(status_code=404, detail="Dette non trouvée")
    
    if data.montant_paye > dette.montant_restant:
        raise HTTPException(status_code=400, detail="Montant supérieur à la dette restante")
    
    paiement = PaiementDette(
        dette_id=dette.id,
        montant_paye=data.montant_paye,
        ip_address=request.client.host
    )
    
    dette.montant_restant -= data.montant_paye
    if dette.montant_restant == 0:
        dette.statut = 'soldee'
    
    db.add(paiement)
    db.commit()
    
    log_audit(db, boutique.id, "debt_payment", "dettes", dette.id, request.client.host)
    
    return {
        "nouveau_solde": dette.montant_restant,
        "statut": dette.statut,
        "paiement_id": paiement.id
    }

@app.post("/api/gemini/parse-voice", response_model=VoiceParseResponse)
async def parse_voice(
    request: Request,
    data: VoiceParseRequest,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    features = json.loads(boutique.features_json)
    voice_quota = features.get("voice_input_quota", 50)
    
    voice_count = db.query(func.count(VoiceLog.id)).filter(
        VoiceLog.boutique_id == boutique.id,
        VoiceLog.created_at >= datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
    ).scalar()
    
    if voice_count >= voice_quota:
        raise HTTPException(status_code=403, detail="Quota vocal épuisé ce mois-ci")
    
    produits = db.query(Produit).filter(
        Produit.boutique_id == boutique.id,
        Produit.active == True,
        Produit.deleted_at == None
    ).all()
    
    produits_list = [{"id": p.id, "nom": p.nom, "prix_unitaire": p.prix_unitaire} for p in produits]
    
    result = parse_voice_input(data.transcript, produits_list)
    
    voice_log = VoiceLog(
        boutique_id=boutique.id,
        transcript=data.transcript,
        parsed_data=json.dumps(result),
        success=result.get("success", False),
        error_message=result.get("error"),
        ip_address=request.client.host
    )
    db.add(voice_log)
    db.commit()
    
    produit_match = None
    if result.get("success") and result.get("produit_nom"):
        for p in produits_list:
            if p["nom"].lower() == result["produit_nom"].lower():
                produit_match = p
                break
    
    return VoiceParseResponse(
        success=result.get("success", False),
        produit=produit_match,
        quantite=result.get("quantite"),
        prix_unitaire=result.get("prix_unitaire"),
        confiance=result.get("confiance", 0.0),
        quota_restant=voice_quota - voice_count - 1
    )

@app.get("/api/objectifs")
async def get_objectifs(
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    objectifs = db.query(Objectif).filter(
        Objectif.boutique_id == boutique.id,
        Objectif.active == True,
        Objectif.deleted_at == None
    ).all()
    
    return [{
        "id": o.id,
        "type": o.type,
        "montant_cible": o.montant_cible,
        "date_debut": o.date_debut.isoformat(),
        "date_fin": o.date_fin.isoformat()
    } for o in objectifs]

@app.post("/api/objectifs")
async def create_objectif(
    request: Request,
    data: ObjectifCreate,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    if data.date_fin <= data.date_debut:
        raise HTTPException(status_code=400, detail="La date de fin doit être après la date de début")
    
    objectif = Objectif(
        boutique_id=boutique.id,
        type=data.type,
        montant_cible=data.montant_cible,
        date_debut=data.date_debut,
        date_fin=data.date_fin
    )
    db.add(objectif)
    db.commit()
    db.refresh(objectif)
    
    return {"id": objectif.id}

CHAT_QUOTA_GRATUIT = 20

@app.post("/api/chat/cecile", response_model=ChatResponse)
async def chat_cecile(
    request: Request,
    data: ChatRequest,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    features = json.loads(boutique.features_json)
    chat_quota = CHAT_QUOTA_GRATUIT if boutique.plan_type == 'gratuit' else 100
    
    chat_count = db.query(func.count(ChatMessage.id)).filter(
        ChatMessage.boutique_id == boutique.id,
        ChatMessage.role == 'user',
        ChatMessage.created_at >= datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
    ).scalar()
    
    if chat_count >= chat_quota:
        return ChatResponse(
            success=False,
            error=f"Quota de messages atteint ({chat_quota}/mois). Passez Premium pour plus de conversations avec Cécile!",
            quota_restant=0,
            quota_max=chat_quota
        )
    
    history = db.query(ChatMessage).filter(
        ChatMessage.boutique_id == boutique.id
    ).order_by(ChatMessage.created_at.desc()).limit(10).all()
    
    history_list = [{"role": m.role, "content": m.content} for m in reversed(history)]
    
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    ventes_aujourdhui = db.query(func.coalesce(func.sum(Vente.montant_total), 0)).filter(
        Vente.boutique_id == boutique.id,
        Vente.date_vente >= today_start,
        Vente.date_vente <= today_end,
        Vente.deleted_at == None
    ).scalar()
    
    dettes_totales = db.query(func.coalesce(func.sum(Dette.montant_restant), 0)).filter(
        Dette.boutique_id == boutique.id,
        Dette.statut == 'en_cours',
        Dette.deleted_at == None
    ).scalar()
    
    stock_alertes = db.query(func.count(Produit.id)).filter(
        Produit.boutique_id == boutique.id,
        Produit.quantite_stock <= Produit.seuil_alerte,
        Produit.active == True,
        Produit.deleted_at == None
    ).scalar()
    
    context = {
        "nom_boutique": boutique.nom,
        "plan_type": boutique.plan_type,
        "ventes_aujourdhui": ventes_aujourdhui,
        "dettes_totales": dettes_totales,
        "stock_alertes": stock_alertes
    }
    
    result = chat_with_cecile(data.message, context, history_list)
    
    user_msg = ChatMessage(
        boutique_id=boutique.id,
        role="user",
        content=data.message
    )
    db.add(user_msg)
    
    if result.get("success") and result.get("response"):
        assistant_msg = ChatMessage(
            boutique_id=boutique.id,
            role="assistant",
            content=result["response"]
        )
        db.add(assistant_msg)
    
    db.commit()
    
    return ChatResponse(
        success=result.get("success", False),
        response=result.get("response"),
        error=result.get("error"),
        quota_restant=chat_quota - chat_count - 1,
        quota_max=chat_quota
    )

@app.get("/api/chat/history")
async def get_chat_history(
    limit: int = 20,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    messages = db.query(ChatMessage).filter(
        ChatMessage.boutique_id == boutique.id
    ).order_by(ChatMessage.created_at.desc()).limit(limit).all()
    
    return [{
        "role": m.role,
        "content": m.content,
        "created_at": m.created_at.isoformat()
    } for m in reversed(messages)]

@app.delete("/api/chat/history")
async def clear_chat_history(
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    db.query(ChatMessage).filter(ChatMessage.boutique_id == boutique.id).delete()
    db.commit()
    return {"success": True}


from .schemas import ChatbotRequest

@app.post("/api/chatbot/message")
async def chatbot_message(
    request: Request,
    data: ChatbotRequest,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    import time
    start_time = time.time()
    
    features = json.loads(boutique.features_json)
    chat_quota = CHAT_QUOTA_GRATUIT if boutique.plan_type == 'gratuit' else 100
    
    chat_count = db.query(func.count(ChatLog.id)).filter(
        ChatLog.boutique_id == boutique.id,
        ChatLog.created_at >= datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
    ).scalar()
    
    if chat_count >= chat_quota:
        return {
            "response": f"Tu as atteint ton quota de messages ({chat_quota}/mois). Passe Premium pour plus de conversations ! 💎",
            "suggestions": ["Voir mes ventes", "Gérer mon stock", "Mes dettes"]
        }
    
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    ventes_aujourdhui = db.query(func.coalesce(func.sum(Vente.montant_total), 0)).filter(
        Vente.boutique_id == boutique.id,
        Vente.date_vente >= today_start,
        Vente.date_vente <= today_end,
        Vente.deleted_at == None
    ).scalar()
    
    depenses_aujourdhui = db.query(func.coalesce(func.sum(Depense.montant), 0)).filter(
        Depense.boutique_id == boutique.id,
        Depense.date_depense >= today_start,
        Depense.date_depense <= today_end,
        Depense.deleted_at == None
    ).scalar()
    
    dettes_totales = db.query(func.coalesce(func.sum(Dette.montant_restant), 0)).filter(
        Dette.boutique_id == boutique.id,
        Dette.statut == 'en_cours',
        Dette.deleted_at == None
    ).scalar()
    
    limite_critique = datetime.utcnow() - timedelta(days=15)
    dettes_critiques = db.query(func.count(Dette.id)).filter(
        Dette.boutique_id == boutique.id,
        Dette.statut == 'en_cours',
        Dette.date_creation <= limite_critique,
        Dette.deleted_at == None
    ).scalar()
    
    stock_alertes = db.query(func.count(Produit.id)).filter(
        Produit.boutique_id == boutique.id,
        Produit.quantite_stock <= Produit.seuil_alerte,
        Produit.active == True,
        Produit.deleted_at == None
    ).scalar()
    
    dettes_liste = db.query(Dette).filter(
        Dette.boutique_id == boutique.id,
        Dette.statut == 'en_cours',
        Dette.deleted_at == None
    ).order_by(Dette.date_creation.asc()).limit(10).all()
    
    dettes_str = ""
    now = datetime.utcnow()
    for d in dettes_liste:
        jours = (now - d.date_creation).days
        dettes_str += f"  - {d.nom_client}: {format_fcfa(d.montant_restant)} (depuis {jours} jours)\n"
    
    ventes_recentes = db.query(Vente).filter(
        Vente.boutique_id == boutique.id,
        Vente.deleted_at == None
    ).order_by(Vente.date_vente.desc()).limit(5).all()
    
    ventes_str = ""
    for v in ventes_recentes:
        ventes_str += f"  - {v.produit.nom}: {v.quantite}x = {format_fcfa(v.montant_total)}\n"
    
    produits_stock_bas = db.query(Produit).filter(
        Produit.boutique_id == boutique.id,
        Produit.quantite_stock <= Produit.seuil_alerte,
        Produit.active == True,
        Produit.deleted_at == None
    ).limit(5).all()
    
    stock_str = ""
    for p in produits_stock_bas:
        stock_str += f"  - {p.nom}: {p.quantite_stock} restant(s)\n"
    
    week_start = today - timedelta(days=7)
    week_start_dt = datetime.combine(week_start, datetime.min.time())
    ventes_semaine = db.query(func.coalesce(func.sum(Vente.montant_total), 0)).filter(
        Vente.boutique_id == boutique.id,
        Vente.date_vente >= week_start_dt,
        Vente.deleted_at == None
    ).scalar()
    
    depenses_semaine = db.query(func.coalesce(func.sum(Depense.montant), 0)).filter(
        Depense.boutique_id == boutique.id,
        Depense.date_depense >= week_start_dt,
        Depense.deleted_at == None
    ).scalar()
    
    benefice_semaine = ventes_semaine - depenses_semaine
    
    context_str = f"""
CONTEXTE BOUTIQUE :
- Nom : {boutique.nom}
- Plan : {boutique.plan_type}

DONNÉES DU JOUR :
- Ventes aujourd'hui : {format_fcfa(ventes_aujourdhui)}
- Dépenses aujourd'hui : {format_fcfa(depenses_aujourdhui)}
- Bénéfice aujourd'hui : {format_fcfa(ventes_aujourdhui - depenses_aujourdhui)}

BILAN DE LA SEMAINE :
- Ventes 7 jours : {format_fcfa(ventes_semaine)}
- Dépenses 7 jours : {format_fcfa(depenses_semaine)}
- Bénéfice net : {format_fcfa(benefice_semaine)}

DETTES EN COURS ({len(dettes_liste)} clients):
{dettes_str if dettes_str else "  Aucune dette en cours"}
Total dettes: {format_fcfa(dettes_totales)} ({dettes_critiques} en retard > 15 jours)

VENTES RÉCENTES:
{ventes_str if ventes_str else "  Aucune vente récente"}

ALERTES STOCK ({stock_alertes} produits):
{stock_str if stock_str else "  Tout le stock est OK"}
"""
    
    history_str = ""
    if data.conversation_history:
        for msg in data.conversation_history[-5:]:
            role = "Utilisateur" if msg.sender == "user" else "Cécile"
            history_str += f"{role}: {msg.text}\n"
    
    is_english = data.language == "en"
    
    if is_english:
        system_prompt = f"""You are Cécile, an intelligent financial assistant for Djassa Coach, an app for Ivorian merchants.

{context_str}

YOUR ROLE:
- Help merchants manage their business
- Respond in simple, accessible English
- Be friendly, encouraging and proactive
- Give actionable advice
- Use emojis sparingly (1-2 max)
- Offer concrete suggestions

CAPABILITIES:
- Analyze sales and give insights
- Advise on debt management
- Suggest savings
- Alert on low stock
- Calculate margins and profits
- Remind about critical debts

STYLE:
- Reply briefly (2-3 sentences max unless detailed analysis requested)
- Be positive and motivating
- Avoid complex financial jargon

RECENT HISTORY:
{history_str}

NEW USER MESSAGE:
{data.message}

INSTRUCTIONS:
1. Respond naturally and conversationally
2. If user asks for numbers, use the context stats
3. If needed, suggest 2-3 quick actions
4. Maintain an encouraging and professional tone

RESPONSE (JSON format):
{{
    "response": "your response here",
    "suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"],
    "proactive_advice": "optional proactive advice if situation warrants it or null"
}}"""
    else:
        system_prompt = f"""Tu es Cécile, l'assistante financière intelligente de Djassa Coach pour les commerçants ivoiriens.

{context_str}

TON RÔLE :
- Aide le commerçant à gérer son business
- Réponds en français simple et accessible
- Sois amicale, encourageante et proactive
- Donne des conseils actionnables
- Utilise des emojis avec parcimonie (1-2 max)
- Propose des suggestions concrètes

CAPACITÉS :
- Analyser les ventes et donner des insights
- Conseiller sur la gestion des dettes
- Suggérer des économies
- Alerter sur les stocks bas
- Calculer des marges et profits
- Rappeler les dettes critiques

STYLE :
- Réponds brièvement (2-3 phrases max sauf si analyse demandée)
- Tutoie l'utilisateur
- Sois positive et motivante
- Évite le jargon financier complexe

HISTORIQUE RÉCENT :
{history_str}

NOUVEAU MESSAGE UTILISATEUR :
{data.message}

INSTRUCTIONS :
1. Réponds de manière naturelle et conversationnelle
2. Si l'utilisateur demande des chiffres, utilise les stats du contexte
3. Si nécessaire, propose 2-3 suggestions d'actions rapides
4. Garde un ton encourageant et professionnel
5. Si les dépenses dépassent les ventes cette semaine, donne un conseil proactif

RÉPONSE (format JSON) :
{{
    "response": "ta réponse ici",
    "suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"],
    "proactive_advice": "conseil proactif optionnel si la situation le justifie ou null"
}}"""

    try:
        from .gemini_service import get_client
        import re
        
        client = get_client()
        if not client:
            response_time_ms = int((time.time() - start_time) * 1000)
            chat_log = ChatLog(
                boutique_id=boutique.id,
                user_message=data.message,
                bot_response="API non configurée",
                success=False,
                response_time_ms=response_time_ms,
                ip_address=request.client.host
            )
            db.add(chat_log)
            db.commit()
            
            return {
                "response": "Désolée, je rencontre un problème technique. Vérifie la configuration de l'API ! 🙏",
                "suggestions": ["Mes ventes aujourd'hui", "Conseils pour économiser", "Mes dettes en retard"]
            }
        
        gemini_response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=system_prompt
        )
        
        text = (gemini_response.text or "").strip()
        
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = {
                "response": text,
                "suggestions": ["Mes ventes aujourd'hui", "Conseils pour économiser", "Mes dettes en retard"] if not is_english else ["My sales today", "Savings tips", "Overdue debts"]
            }
        
        transaction_recorded = None
        auto_tx_feedback = None
        
        if data.auto_record_transactions:
            five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
            recent_auto_tx_count = db.query(func.count(ChatLog.id)).filter(
                ChatLog.boutique_id == boutique.id,
                ChatLog.created_at >= five_minutes_ago,
                ChatLog.bot_response.like("%enregistrée:%") | ChatLog.bot_response.like("%recorded:%")
            ).scalar() or 0
            
            if recent_auto_tx_count >= 10:
                auto_tx_feedback = "Trop de transactions automatiques récentes. Utilisez les formulaires pour continuer." if not is_english else "Too many recent automatic transactions. Please use the forms to continue."
            else:
                produits_for_detection = [{
                    "id": p.id,
                    "nom": p.nom,
                    "prix_unitaire": p.prix_unitaire,
                    "quantite_stock": p.quantite_stock
                } for p in db.query(Produit).filter(
                    Produit.boutique_id == boutique.id,
                    Produit.active == True,
                    Produit.deleted_at == None
                ).limit(30).all()]
                
                intent = detect_transaction_intent(data.message, produits_for_detection, data.language)
                
                if intent.get("has_transaction") and intent.get("confidence", 0) >= 0.8:
                    tx_type = intent.get("transaction_type")
                    details = intent.get("details", {})
                    
                    if tx_type == "vente":
                        produit_nom = details.get("produit_nom")
                        quantite = details.get("quantite")
                        
                        if produit_nom and isinstance(produit_nom, str) and len(produit_nom) >= 2:
                            if quantite and isinstance(quantite, (int, float)) and quantite >= 1:
                                quantite = int(quantite)
                                
                                produit = db.query(Produit).filter(
                                    Produit.boutique_id == boutique.id,
                                    func.lower(Produit.nom).like(f"%{produit_nom.lower()}%"),
                                    Produit.active == True,
                                    Produit.deleted_at == None
                                ).first()
                                
                                if produit and produit.quantite_stock >= quantite:
                                    montant_total = quantite * produit.prix_unitaire
                                    vente = Vente(
                                        boutique_id=boutique.id,
                                        produit_id=produit.id,
                                        quantite=quantite,
                                        prix_unitaire=produit.prix_unitaire,
                                        montant_total=montant_total
                                    )
                                    produit.quantite_stock -= quantite
                                    db.add(vente)
                                    db.commit()
                                    
                                    log_audit(db, boutique.id, "create_auto", "ventes", str(vente.id), request.client.host, None, {"source": "cecile", "produit": produit.nom, "quantite": quantite})
                                    
                                    tx_msg = f"Vente enregistrée: {quantite}x {produit.nom} = {format_fcfa(montant_total)}" if not is_english else f"Sale recorded: {quantite}x {produit.nom} = {format_fcfa(montant_total)}"
                                    transaction_recorded = {
                                        "type": "vente",
                                        "details": {"produit": produit.nom, "quantite": quantite, "montant": montant_total},
                                        "success": True,
                                        "message": tx_msg
                                    }
                                    result["response"] = f"C'est noté ! {tx_msg} 💪" if not is_english else f"Got it! {tx_msg} 💪"
                                elif produit and produit.quantite_stock < quantite:
                                    auto_tx_feedback = f"Stock insuffisant pour {produit.nom} ({produit.quantite_stock} disponible). Ajoutez du stock d'abord." if not is_english else f"Insufficient stock for {produit.nom} ({produit.quantite_stock} available). Add stock first."
                                elif not produit:
                                    auto_tx_feedback = f"Produit '{produit_nom}' non trouvé. Ajoutez-le dans le stock d'abord." if not is_english else f"Product '{produit_nom}' not found. Add it to stock first."
                            else:
                                auto_tx_feedback = "Précisez la quantité (ex: '2 sacs de riz')." if not is_english else "Specify the quantity (e.g., '2 bags of rice')."
                        else:
                            auto_tx_feedback = "Précisez le produit (ex: 'vendu 3 savons')." if not is_english else "Specify the product (e.g., 'sold 3 soaps')."
                    
                    elif tx_type == "depense":
                        montant = details.get("montant_total")
                        
                        if montant and isinstance(montant, (int, float)) and montant >= 100:
                            montant = int(montant)
                            categorie = details.get("categorie") or "Autre"
                            description = details.get("description") or ""
                            
                            if isinstance(categorie, str) and len(categorie) >= 2:
                                depense = Depense(
                                    boutique_id=boutique.id,
                                    categorie=categorie,
                                    montant=montant,
                                    description=description[:500] if isinstance(description, str) else ""
                                )
                                db.add(depense)
                                db.commit()
                                
                                log_audit(db, boutique.id, "create_auto", "depenses", str(depense.id), request.client.host, None, {"source": "cecile", "categorie": categorie, "montant": montant})
                                
                                tx_msg = f"Dépense enregistrée: {format_fcfa(montant)} ({categorie})" if not is_english else f"Expense recorded: {format_fcfa(montant)} ({categorie})"
                                transaction_recorded = {
                                    "type": "depense",
                                    "details": {"categorie": categorie, "montant": montant},
                                    "success": True,
                                    "message": tx_msg
                                }
                                result["response"] = f"C'est noté ! {tx_msg} 📝" if not is_english else f"Got it! {tx_msg} 📝"
                        else:
                            auto_tx_feedback = "Précisez le montant de la dépense (minimum 100 FCFA)." if not is_english else "Specify the expense amount (minimum 100 FCFA)."
                    
                    elif tx_type == "dette":
                        client_nom = details.get("client_nom")
                        montant = details.get("montant_total")
                        
                        if client_nom and isinstance(client_nom, str) and len(client_nom) >= 2:
                            if montant and isinstance(montant, (int, float)) and montant >= 500:
                                montant = int(montant)
                                
                                dette = Dette(
                                    boutique_id=boutique.id,
                                    nom_client=client_nom[:100],
                                    montant_initial=montant,
                                    montant_restant=montant
                                )
                                db.add(dette)
                                db.commit()
                                
                                log_audit(db, boutique.id, "create_auto", "dettes", str(dette.id), request.client.host, None, {"source": "cecile", "client": client_nom, "montant": montant})
                                
                                tx_msg = f"Dette enregistrée: {client_nom} doit {format_fcfa(montant)}" if not is_english else f"Debt recorded: {client_nom} owes {format_fcfa(montant)}"
                                transaction_recorded = {
                                    "type": "dette",
                                    "details": {"client": client_nom, "montant": montant},
                                    "success": True,
                                    "message": tx_msg
                                }
                                result["response"] = f"C'est noté ! {tx_msg} 📋" if not is_english else f"Got it! {tx_msg} 📋"
                            else:
                                auto_tx_feedback = "Précisez le montant de la dette (minimum 500 FCFA)." if not is_english else "Specify the debt amount (minimum 500 FCFA)."
                        else:
                            auto_tx_feedback = "Précisez le nom du client." if not is_english else "Specify the client's name."
        
        if transaction_recorded:
            result["transaction_recorded"] = transaction_recorded
        
        if auto_tx_feedback and not transaction_recorded:
            if result.get("response"):
                result["response"] = result["response"] + f"\n\n💡 {auto_tx_feedback}"
            else:
                result["response"] = auto_tx_feedback
        
        proactive_advice = result.get("proactive_advice")
        if depenses_semaine > ventes_semaine and not proactive_advice:
            if not is_english:
                proactive_advice = f"⚠️ Attention: tes dépenses cette semaine ({format_fcfa(depenses_semaine)}) dépassent tes ventes ({format_fcfa(ventes_semaine)}). Essaie de réduire les dépenses non essentielles."
            else:
                proactive_advice = f"⚠️ Warning: your expenses this week ({format_fcfa(depenses_semaine)}) exceed your sales ({format_fcfa(ventes_semaine)}). Try to reduce non-essential expenses."
            result["proactive_advice"] = proactive_advice
        
        response_time_ms = int((time.time() - start_time) * 1000)
        
        chat_log = ChatLog(
            boutique_id=boutique.id,
            user_message=data.message,
            bot_response=result.get("response", ""),
            success=True,
            response_time_ms=response_time_ms,
            ip_address=request.client.host
        )
        db.add(chat_log)
        db.commit()
        
        return result
        
    except json.JSONDecodeError as json_err:
        response_time_ms = int((time.time() - start_time) * 1000)
        fallback_response = "Désolée, j'ai rencontré un problème technique. Pouvez-vous reformuler votre question ? 🙏"
        chat_log = ChatLog(
            boutique_id=boutique.id,
            user_message=data.message,
            bot_response=f"Erreur JSON: {str(json_err)}",
            success=False,
            response_time_ms=response_time_ms,
            ip_address=request.client.host
        )
        db.add(chat_log)
        db.commit()
        
        return {
            "response": fallback_response,
            "suggestions": ["Mes ventes aujourd'hui", "Conseils pour économiser", "Mes dettes en retard"]
        }
    except Exception as e:
        response_time_ms = int((time.time() - start_time) * 1000)
        chat_log = ChatLog(
            boutique_id=boutique.id,
            user_message=data.message,
            bot_response=str(e),
            success=False,
            response_time_ms=response_time_ms,
            ip_address=request.client.host
        )
        db.add(chat_log)
        db.commit()
        
        return {
            "response": "Désolée, j'ai rencontré un problème technique. Pouvez-vous réessayer ? 🙏",
            "suggestions": ["Mes ventes aujourd'hui", "Conseils pour économiser", "Mes dettes en retard"]
        }


@app.get("/api/reports/net-profit")
async def get_net_profit(
    periode: str = "jour",
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    today = date.today()
    days = 7 if periode in ["jour", "semaine"] else 14
    start_date = today - timedelta(days=days)
    start_dt = datetime.combine(start_date, datetime.min.time())
    
    ventes_total = db.query(func.coalesce(func.sum(Vente.montant_total), 0)).filter(
        Vente.boutique_id == boutique.id,
        Vente.date_vente >= start_dt,
        Vente.deleted_at == None
    ).scalar()
    
    depenses_total = db.query(func.coalesce(func.sum(Depense.montant), 0)).filter(
        Depense.boutique_id == boutique.id,
        Depense.date_depense >= start_dt,
        Depense.deleted_at == None
    ).scalar()
    
    return {
        "ventes": int(ventes_total),
        "depenses": int(depenses_total),
        "benefice_net": int(ventes_total) - int(depenses_total)
    }


@app.get("/api/reports/{report_type}")
async def get_reports(
    report_type: str,
    periode: str = "jour",
    date_debut: str = None,
    boutique: Boutique = Depends(get_current_boutique),
    db: Session = Depends(get_db)
):
    today = date.today()
    
    if date_debut:
        try:
            start_date = datetime.strptime(date_debut, "%Y-%m-%d").date()
        except:
            start_date = today
    else:
        start_date = today
    
    days = 7 if periode in ["jour", "semaine"] else 14
    
    report_data = []
    total = 0
    
    if report_type == "ventes":
        for i in range(days):
            current_date = start_date - timedelta(days=i)
            date_start = datetime.combine(current_date, datetime.min.time())
            date_end = datetime.combine(current_date, datetime.max.time())
            
            montant = db.query(func.coalesce(func.sum(Vente.montant_total), 0)).filter(
                Vente.boutique_id == boutique.id,
                Vente.date_vente >= date_start,
                Vente.date_vente <= date_end,
                Vente.deleted_at == None
            ).scalar()
            
            count = db.query(func.count(Vente.id)).filter(
                Vente.boutique_id == boutique.id,
                Vente.date_vente >= date_start,
                Vente.date_vente <= date_end,
                Vente.deleted_at == None
            ).scalar()
            
            report_data.append({
                "date": current_date.isoformat(),
                "montantTotal": int(montant),
                "nombreTransactions": count
            })
            total += int(montant)
    
    elif report_type == "depenses":
        for i in range(days):
            current_date = start_date - timedelta(days=i)
            date_start = datetime.combine(current_date, datetime.min.time())
            date_end = datetime.combine(current_date, datetime.max.time())
            
            montant = db.query(func.coalesce(func.sum(Depense.montant), 0)).filter(
                Depense.boutique_id == boutique.id,
                Depense.date_depense >= date_start,
                Depense.date_depense <= date_end,
                Depense.deleted_at == None
            ).scalar()
            
            count = db.query(func.count(Depense.id)).filter(
                Depense.boutique_id == boutique.id,
                Depense.date_depense >= date_start,
                Depense.date_depense <= date_end,
                Depense.deleted_at == None
            ).scalar()
            
            report_data.append({
                "date": current_date.isoformat(),
                "montantTotal": int(montant),
                "nombreTransactions": count
            })
            total += int(montant)
    
    elif report_type == "dettes":
        dettes = db.query(Dette).filter(
            Dette.boutique_id == boutique.id,
            Dette.statut == 'en_cours',
            Dette.deleted_at == None
        ).order_by(Dette.date_creation.desc()).all()
        
        for dette in dettes:
            report_data.append({
                "date": dette.date_creation.date().isoformat(),
                "montantTotal": int(dette.montant_restant),
                "nombreTransactions": 1,
                "client": dette.nom_client
            })
            total += int(dette.montant_restant)
    
    elif report_type == "stock":
        produits = db.query(Produit).filter(
            Produit.boutique_id == boutique.id,
            Produit.active == True,
            Produit.deleted_at == None
        ).order_by(Produit.quantite_stock.asc()).all()
        
        for p in produits:
            valeur = p.prix_unitaire * p.quantite_stock
            report_data.append({
                "date": p.nom,
                "montantTotal": int(valeur),
                "nombreTransactions": p.quantite_stock,
                "alerte": p.quantite_stock <= p.seuil_alerte
            })
            total += int(valeur)
    
    average = total / days if days > 0 else 0
    
    prev_start = start_date - timedelta(days=days)
    prev_total = 0
    
    if report_type == "ventes":
        for i in range(days):
            current_date = prev_start - timedelta(days=i)
            date_start = datetime.combine(current_date, datetime.min.time())
            date_end = datetime.combine(current_date, datetime.max.time())
            montant = db.query(func.coalesce(func.sum(Vente.montant_total), 0)).filter(
                Vente.boutique_id == boutique.id,
                Vente.date_vente >= date_start,
                Vente.date_vente <= date_end,
                Vente.deleted_at == None
            ).scalar()
            prev_total += int(montant)
    elif report_type == "depenses":
        for i in range(days):
            current_date = prev_start - timedelta(days=i)
            date_start = datetime.combine(current_date, datetime.min.time())
            date_end = datetime.combine(current_date, datetime.max.time())
            montant = db.query(func.coalesce(func.sum(Depense.montant), 0)).filter(
                Depense.boutique_id == boutique.id,
                Depense.date_depense >= date_start,
                Depense.date_depense <= date_end,
                Depense.deleted_at == None
            ).scalar()
            prev_total += int(montant)
    
    trend = 0
    if prev_total > 0:
        trend = round(((total - prev_total) / prev_total) * 100)
    
    return {
        "data": report_data,
        "summary": {
            "total": total,
            "average": round(average),
            "trend": trend
        }
    }

static_path = os.path.join(os.path.dirname(__file__), "../../frontend/dist")
if os.path.exists(static_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(static_path, "assets")), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join(static_path, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(static_path, "index.html"))
