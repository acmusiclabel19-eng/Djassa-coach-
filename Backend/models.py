from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey, CheckConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from .database import Base

def generate_uuid():
    return str(uuid.uuid4()).replace('-', '')

class Boutique(Base):
    __tablename__ = "boutiques"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    nom = Column(String(100), nullable=False)
    telephone = Column(String(20), unique=True, nullable=False)
    pin_hash = Column(String(128), nullable=False)
    pin_salt = Column(String(64), nullable=False)
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    plan_type = Column(String(20), default='gratuit')
    plan_expire_at = Column(DateTime, nullable=True)
    max_boutiques = Column(Integer, default=1)
    features_json = Column(Text, default='{"max_boutiques":1,"max_transactions_mois":100,"voice_input_quota":50,"sms_reminders":false,"excel_export":false,"objectives":true,"analytics_retention_days":7,"mobile_money":false,"priority_support":false}')
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(50), nullable=True)
    active = Column(Boolean, default=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    produits = relationship("Produit", back_populates="boutique", cascade="all, delete-orphan")
    ventes = relationship("Vente", back_populates="boutique", cascade="all, delete-orphan")
    depenses = relationship("Depense", back_populates="boutique", cascade="all, delete-orphan")
    dettes = relationship("Dette", back_populates="boutique", cascade="all, delete-orphan")
    objectifs = relationship("Objectif", back_populates="boutique", cascade="all, delete-orphan")
    voice_logs = relationship("VoiceLog", back_populates="boutique", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="boutique", cascade="all, delete-orphan")

class Produit(Base):
    __tablename__ = "produits"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    nom = Column(String(100), nullable=False)
    prix_unitaire = Column(Integer, nullable=False)
    quantite_stock = Column(Integer, default=0)
    seuil_alerte = Column(Integer, default=5)
    categorie = Column(String(50), nullable=True)
    code_barre = Column(String(100), unique=True, nullable=True)
    active = Column(Boolean, default=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    boutique = relationship("Boutique", back_populates="produits")
    ventes = relationship("Vente", back_populates="produit")

class Vente(Base):
    __tablename__ = "ventes"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    produit_id = Column(String(32), ForeignKey("produits.id", ondelete="RESTRICT"), nullable=False)
    quantite = Column(Integer, nullable=False)
    prix_unitaire = Column(Integer, nullable=False)
    montant_total = Column(Integer, nullable=False)
    mode_paiement = Column(String(20), default='especes')
    reference_paiement = Column(String(100), nullable=True)
    date_vente = Column(DateTime, default=datetime.utcnow)
    synced = Column(Boolean, default=False)
    ip_address = Column(String(50), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    boutique = relationship("Boutique", back_populates="ventes")
    produit = relationship("Produit", back_populates="ventes")

class Depense(Base):
    __tablename__ = "depenses"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    categorie = Column(String(50), nullable=False)
    montant = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    recu_url = Column(String(500), nullable=True)
    date_depense = Column(DateTime, default=datetime.utcnow)
    synced = Column(Boolean, default=False)
    ip_address = Column(String(50), nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    boutique = relationship("Boutique", back_populates="depenses")

class Dette(Base):
    __tablename__ = "dettes"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    nom_client = Column(String(100), nullable=False)
    telephone_client = Column(String(20), nullable=True)
    montant_initial = Column(Integer, nullable=False)
    montant_restant = Column(Integer, nullable=False)
    date_creation = Column(DateTime, default=datetime.utcnow)
    date_echeance = Column(DateTime, nullable=True)
    statut = Column(String(20), default='en_cours')
    rappels_envoyes = Column(Integer, default=0)
    synced = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    boutique = relationship("Boutique", back_populates="dettes")
    paiements = relationship("PaiementDette", back_populates="dette", cascade="all, delete-orphan")

class PaiementDette(Base):
    __tablename__ = "paiements_dettes"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    dette_id = Column(String(32), ForeignKey("dettes.id", ondelete="CASCADE"), nullable=False)
    montant_paye = Column(Integer, nullable=False)
    mode_paiement = Column(String(20), default='especes')
    reference_paiement = Column(String(100), nullable=True)
    date_paiement = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    dette = relationship("Dette", back_populates="paiements")

class Objectif(Base):
    __tablename__ = "objectifs"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(20), nullable=False)
    montant_cible = Column(Integer, nullable=False)
    date_debut = Column(DateTime, nullable=False)
    date_fin = Column(DateTime, nullable=False)
    active = Column(Boolean, default=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    boutique = relationship("Boutique", back_populates="objectifs")

class VoiceLog(Base):
    __tablename__ = "voice_logs"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    transcript = Column(Text, nullable=False)
    parsed_data = Column(Text, nullable=True)
    success = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    boutique = relationship("Boutique", back_populates="voice_logs")

class Session(Base):
    __tablename__ = "sessions"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(256), unique=True, nullable=False)
    ip_address = Column(String(50), nullable=False)
    user_agent = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    boutique = relationship("Boutique", back_populates="sessions")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(50), nullable=False)
    table_name = Column(String(50), nullable=True)
    record_id = Column(String(32), nullable=True)
    old_values = Column(Text, nullable=True)
    new_values = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=False)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class ChatLog(Base):
    __tablename__ = "chat_logs"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    user_message = Column(Text, nullable=False)
    bot_response = Column(Text, nullable=False)
    success = Column(Boolean, default=True)
    response_time_ms = Column(Integer, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_chat_logs_boutique', 'boutique_id', 'created_at'),
    )

class FrequentDepense(Base):
    __tablename__ = "frequent_depenses"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    categorie = Column(String(50), nullable=False)
    montant_bucket = Column(Integer, nullable=False)
    usage_count = Column(Integer, default=1)
    last_used_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_frequent_depenses_boutique', 'boutique_id', 'usage_count'),
    )

class DepenseCategory(Base):
    __tablename__ = "depense_categories"
    
    id = Column(String(32), primary_key=True, default=generate_uuid)
    boutique_id = Column(String(32), ForeignKey("boutiques.id", ondelete="CASCADE"), nullable=False)
    nom = Column(String(50), nullable=False)
    icone = Column(String(10), nullable=False)
    usage_count = Column(Integer, default=0)
    active = Column(Boolean, default=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_depense_categories_boutique', 'boutique_id', 'usage_count'),
    )
